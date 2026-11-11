"""
mt5_client.py - pembungkus library MetaTrader5.

TAHAP 1: file ini hanya MEMBACA data (akun, harga, candle).
Tidak ada fungsi untuk mengirim order.
"""
from dataclasses import dataclass
from typing import List, Optional

import MetaTrader5 as mt5
import pandas as pd

from .config import Config


class MT5Error(Exception):
    """Kesalahan saat berkomunikasi dengan MT5."""


TRADE_MODE_NAMES = {
    mt5.ACCOUNT_TRADE_MODE_DEMO: "DEMO",
    mt5.ACCOUNT_TRADE_MODE_CONTEST: "CONTEST",
    mt5.ACCOUNT_TRADE_MODE_REAL: "REAL",
}

MARGIN_MODE_NAMES = {
    mt5.ACCOUNT_MARGIN_MODE_RETAIL_NETTING: "Netting",
    mt5.ACCOUNT_MARGIN_MODE_EXCHANGE: "Exchange",
    mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING: "Hedging",
}


@dataclass
class AccountSummary:
    login: int
    name: str
    server: str
    currency: str
    balance: float
    equity: float
    leverage: int
    mode: str  # DEMO / REAL / CONTEST
    margin_mode: str  # Netting / Hedging / Exchange
    trade_allowed: bool


@dataclass
class SymbolSummary:
    name: str
    description: str
    digits: int
    point: float
    bid: float
    ask: float
    spread_points: int
    tick_time: Optional[pd.Timestamp]  # waktu server broker
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    stops_level: int


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str


class MT5Client:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ------------------------------------------------------------------
    # koneksi
    # ------------------------------------------------------------------
    def connect(self) -> None:
        kwargs = {}
        if self.cfg.mt5_path:
            kwargs["path"] = self.cfg.mt5_path

        if not mt5.initialize(**kwargs):
            raise MT5Error(
                f"Gagal memulai MT5: {mt5.last_error()}\n"
                "Pastikan aplikasi MetaTrader 5 sudah terpasang dan sebaiknya sudah terbuka."
            )

        if not mt5.login(self.cfg.account, password=self.cfg.password, server=self.cfg.server):
            err = mt5.last_error()
            mt5.shutdown()
            raise MT5Error(
                f"Login gagal: {err}\n"
                "Cek ACCOUNT, PASSWORD, dan SERVER di .env (nama server harus persis seperti di MT5)."
            )

    def shutdown(self) -> None:
        mt5.shutdown()

    def prepare_symbol(self) -> None:
        """Pastikan simbol ada dan tampil di Market Watch."""
        symbol = self.cfg.symbol
        info = mt5.symbol_info(symbol)
        if info is None:
            found = mt5.symbols_get("*XAU*") or []
            names = [s.name for s in found][:10]
            hint = f" Simbol mirip yang ada di broker Anda: {', '.join(names)}." if names else ""
            raise MT5Error(f"Simbol '{symbol}' tidak ditemukan di broker.{hint}")
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise MT5Error(f"Gagal menampilkan simbol '{symbol}' di Market Watch: {mt5.last_error()}")

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------
    def get_account(self) -> AccountSummary:
        acc = mt5.account_info()
        if acc is None:
            raise MT5Error(f"Gagal membaca info akun: {mt5.last_error()}")
        return AccountSummary(
            login=acc.login,
            name=acc.name,
            server=acc.server,
            currency=acc.currency,
            balance=acc.balance,
            equity=acc.equity,
            leverage=acc.leverage,
            mode=TRADE_MODE_NAMES.get(acc.trade_mode, str(acc.trade_mode)),
            margin_mode=MARGIN_MODE_NAMES.get(acc.margin_mode, str(acc.margin_mode)),
            trade_allowed=bool(acc.trade_allowed),
        )

    def get_symbol(self) -> SymbolSummary:
        symbol = self.cfg.symbol
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(f"Gagal membaca simbol '{symbol}': {mt5.last_error()}")

        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.bid and tick.ask:
            bid, ask = float(tick.bid), float(tick.ask)
            tick_time = pd.to_datetime(tick.time, unit="s")
        else:
            bid = ask = 0.0
            tick_time = None

        if bid and ask and info.point:
            spread_points = int(round((ask - bid) / info.point))
        else:
            spread_points = int(info.spread)

        return SymbolSummary(
            name=info.name,
            description=info.description,
            digits=info.digits,
            point=info.point,
            bid=bid,
            ask=ask,
            spread_points=spread_points,
            tick_time=tick_time,
            contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_step=info.volume_step,
            volume_max=info.volume_max,
            stops_level=int(info.trade_stops_level),
        )

    def get_candles(self, count: int = 15) -> pd.DataFrame:
        """Candle M1 terbaru. Kolom waktu memakai waktu server broker."""
        rates = mt5.copy_rates_from_pos(self.cfg.symbol, mt5.TIMEFRAME_M1, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume", "spread"])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]

    # ------------------------------------------------------------------
    # pemeriksaan siap-jalan
    # ------------------------------------------------------------------
    def run_checks(self, account: AccountSummary, sym: SymbolSummary, candles: pd.DataFrame) -> List[Check]:
        checks: List[Check] = []
        term = mt5.terminal_info()

        # koneksi
        if term is not None and term.connected:
            checks.append(Check("Koneksi ke server broker", "ok", account.server))
        else:
            checks.append(Check("Koneksi ke server broker", "fail", "Terminal tidak terhubung ke server"))

        # demo / real
        if account.mode == "DEMO":
            checks.append(Check("Jenis akun", "ok", "DEMO"))
        else:
            checks.append(Check("Jenis akun", "warn", f"{account.mode} - uang sungguhan, hati-hati"))

        # tipe margin
        extra = "satu posisi gabungan per simbol" if account.margin_mode == "Netting" else ""
        checks.append(Check("Tipe akun", "ok", f"{account.margin_mode} {('(' + extra + ')') if extra else ''}".strip()))

        # algo trading
        if term is not None and term.trade_allowed:
            checks.append(Check("Algo Trading di terminal", "ok", "Aktif"))
        else:
            checks.append(Check("Algo Trading di terminal", "warn", "Mati - klik tombol Algo Trading di MT5 sampai hijau"))

        if account.trade_allowed:
            checks.append(Check("Trading diizinkan untuk akun", "ok", "Ya"))
        else:
            checks.append(Check("Trading diizinkan untuk akun", "warn", "Tidak diizinkan oleh broker"))

        # simbol & data
        checks.append(Check("Simbol", "ok", f"{sym.name} - {sym.description}"))
        if len(candles) > 0:
            checks.append(Check("Data candle M1", "ok", f"{len(candles)} candle terbaca"))
        else:
            checks.append(Check("Data candle M1", "warn", "Kosong - cek koneksi atau buka chart simbol di MT5"))

        # lot
        checks.append(self._check_lot(sym))

        # spread
        if sym.bid == 0:
            checks.append(Check("Spread", "warn", "Belum ada harga masuk (pasar mungkin tutup)"))
        elif self.cfg.max_spread is None:
            checks.append(Check("Spread", "warn", f"{sym.spread_points} poin. MAX_SPREAD belum diisi"))
        elif sym.spread_points > self.cfg.max_spread:
            checks.append(Check("Spread", "warn", f"{sym.spread_points} poin, di atas batas {self.cfg.max_spread:g}"))
        else:
            checks.append(Check("Spread", "ok", f"{sym.spread_points} poin (batas {self.cfg.max_spread:g})"))

        return checks

    def _check_lot(self, sym: SymbolSummary) -> Check:
        lot = self.cfg.lot_size
        eps = 1e-9
        if lot < sym.volume_min - eps or lot > sym.volume_max + eps:
            return Check("Lot", "fail", f"{lot:g} di luar batas broker ({sym.volume_min:g} - {sym.volume_max:g})")
        if sym.volume_step > 0:
            steps = (lot - sym.volume_min) / sym.volume_step
            if abs(steps - round(steps)) > 1e-6:
                return Check("Lot", "fail", f"{lot:g} tidak sesuai kelipatan {sym.volume_step:g}")
        return Check("Lot", "ok", f"{lot:g} (min {sym.volume_min:g}, kelipatan {sym.volume_step:g})")