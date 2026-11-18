"""
mt5_client.py - pembungkus library MetaTrader5.

TAHAP 1: koneksi dan baca data.
TAHAP 4: tambah fungsi order (kirim, ubah SL, tutup, baca posisi, baca riwayat deal).
         Semua logika order di sini; modul lain tidak meng-import MetaTrader5.
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

# Magic number tetap untuk posisi bot - bukan diubah via konfigurasi
BOT_MAGIC = 20261116


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


@dataclass
class OrderResult:
    success: bool
    ticket: int        # 0 jika gagal
    retcode: int
    comment: str
    entry_price: float  # harga eksekusi sebenarnya


@dataclass
class PositionInfo:
    ticket: int
    side: int           # 1=buy, -1=sell
    symbol: str
    volume: float
    entry_price: float
    sl: float
    open_time: pd.Timestamp


@dataclass
class DealInfo:
    ticket: int
    position_id: int
    side: int           # 1=buy, -1=sell (arah deal penutup)
    price: float
    volume: float
    profit: float
    commission: float
    swap: float
    time: pd.Timestamp
    comment: str
    reason: int         # mt5.DEAL_REASON_*


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

    # ------------------------------------------------------------------
    # ORDER: validasi pra-order
    # ------------------------------------------------------------------
    def _validate_pre_order(self, side: int, sl_price: float) -> str:
        """
        Validasi pra-order sebelum mengirim ke MT5.
        Kembalikan string error jika gagal, atau "" jika lolos.
        side: 1=buy, -1=sell.
        sl_price: harga SL yang direncanakan.
        """
        # 1. Algo Trading di terminal
        term = mt5.terminal_info()
        if term is None or not term.trade_allowed:
            return "Algo Trading tidak aktif di terminal MT5. Klik tombol Algo Trading sampai hijau."

        # 2. Account trade_allowed
        acc = mt5.account_info()
        if acc is None:
            return f"Gagal membaca info akun: {mt5.last_error()}"
        if not acc.trade_allowed:
            return "Trading tidak diizinkan untuk akun ini."

        # 3. Jenis akun: REAL hanya jika ALLOW_REAL=true
        if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL and not self.cfg.allow_real:
            return (
                "KEAMANAN: Ini akun REAL. Bot menolak order ke akun REAL "
                "kecuali ALLOW_REAL=true di .env dan dikonfirmasi pengguna."
            )

        # 4. Symbol info
        sym_info = mt5.symbol_info(self.cfg.symbol)
        if sym_info is None:
            return f"Gagal membaca info simbol {self.cfg.symbol}: {mt5.last_error()}"
        if sym_info.trade_mode not in (
            mt5.SYMBOL_TRADE_MODE_FULL,
            mt5.SYMBOL_TRADE_MODE_LONGONLY,
            mt5.SYMBOL_TRADE_MODE_SHORTONLY,
        ):
            return f"Pasar tutup atau trading tidak diizinkan untuk {self.cfg.symbol} saat ini."

        # 5. Tick segar (harga valid)
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None or tick.bid == 0:
            return "Tidak ada tick terbaru untuk simbol ini. Pasar mungkin tutup."

        # 6. Normalisasi harga dan cek jarak SL >= stops_level
        point = sym_info.point
        stops_level = int(sym_info.trade_stops_level)
        freeze_level = int(sym_info.trade_freeze_level)
        price = float(tick.ask) if side == 1 else float(tick.bid)
        sl_dist_points = abs(price - sl_price) / point
        min_dist = max(stops_level, freeze_level) + 1
        if sl_dist_points < min_dist:
            return (
                f"Jarak SL terlalu dekat: {sl_dist_points:.1f} poin, "
                f"minimum broker {min_dist} poin."
            )

        # 7. Volume
        lot = self.cfg.lot_size
        if lot < sym_info.volume_min or lot > sym_info.volume_max:
            return (
                f"Lot {lot:g} di luar batas broker "
                f"({sym_info.volume_min:g} - {sym_info.volume_max:g})."
            )

        return ""

    def _get_filling_mode(self, sym_info) -> Optional[int]:
        """
        Deteksi filling mode yang didukung simbol ini dari sym_info.filling_mode.
        Urutan preferensi: FOK -> IOC -> Return.
        Kembalikan None jika tidak ada yang cocok.
        """
        filling = int(sym_info.filling_mode)
        if filling & 1:   # bit 0 = FOK
            return mt5.ORDER_FILLING_FOK
        if filling & 2:   # bit 1 = IOC
            return mt5.ORDER_FILLING_IOC
        if filling & 4:   # bit 2 = Return
            return mt5.ORDER_FILLING_RETURN
        # Fallback
        return mt5.ORDER_FILLING_FOK

    # ------------------------------------------------------------------
    # ORDER: kirim order pasar
    # ------------------------------------------------------------------
    def send_market_order(self, side: int, sl_distance: float) -> OrderResult:
        """
        Kirim order pasar dengan SL.
        side: 1=BUY, -1=SELL
        sl_distance: jarak SL dalam satuan harga (1R)
        Kembalikan OrderResult.
        """
        symbol = self.cfg.symbol
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            return OrderResult(False, 0, -1, f"symbol_info gagal: {mt5.last_error()}", 0.0)

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid == 0:
            return OrderResult(False, 0, -1, "Tidak ada tick terbaru", 0.0)

        digits = sym_info.digits
        price = round(float(tick.ask) if side == 1 else float(tick.bid), digits)

        # Hitung SL
        if side == 1:
            sl = round(price - sl_distance, digits)
        else:
            sl = round(price + sl_distance, digits)

        # Validasi pra-order
        err = self._validate_pre_order(side, sl)
        if err:
            return OrderResult(False, 0, -1, err, 0.0)

        # Filling mode dari simbol
        filling = self._get_filling_mode(sym_info)

        order_type = mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL
        deviation = getattr(self.cfg, "max_slippage_points", 30)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": self.cfg.lot_size,
            "type": order_type,
            "price": price,
            "sl": sl,
            "deviation": deviation,
            "magic": BOT_MAGIC,
            "comment": "bot-xau",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        # mt5.order_check sebelum order_send
        check_result = mt5.order_check(request)
        if check_result is None:
            return OrderResult(False, 0, -1, f"order_check gagal: {mt5.last_error()}", 0.0)
        if check_result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                False, 0, check_result.retcode,
                f"order_check ditolak: {check_result.comment} (retcode {check_result.retcode})",
                0.0,
            )

        result = mt5.order_send(request)
        if result is None:
            return OrderResult(False, 0, -1, f"order_send None: {mt5.last_error()}", 0.0)

        return self._handle_order_result(result, price)

    def _handle_order_result(self, result, expected_price: float) -> OrderResult:
        """Tangani retcode secara eksplisit."""
        rc = result.retcode

        if rc == mt5.TRADE_RETCODE_DONE:
            return OrderResult(True, result.order, rc, result.comment, float(result.price))

        # Retcode yang bisa dicoba ulang (loop luar yang menentukan apakah coba lagi)
        retriable = {
            mt5.TRADE_RETCODE_REQUOTE,
            mt5.TRADE_RETCODE_PRICE_CHANGED,
            mt5.TRADE_RETCODE_PRICE_OFF,
            mt5.TRADE_RETCODE_TIMEOUT,
            mt5.TRADE_RETCODE_CONNECTION,
        }
        if rc in retriable:
            return OrderResult(False, 0, rc, f"Coba lagi: {result.comment} ({rc})", 0.0)

        # Error fatal - tidak perlu coba lagi
        fatal_map = {
            mt5.TRADE_RETCODE_REJECT: "Order ditolak broker",
            mt5.TRADE_RETCODE_INVALID_STOPS: "Jarak SL tidak valid (terlalu dekat?)",
            mt5.TRADE_RETCODE_INVALID_FILL: "Filling mode tidak didukung simbol",
            mt5.TRADE_RETCODE_MARKET_CLOSED: "Pasar ditutup",
            mt5.TRADE_RETCODE_NO_MONEY: "Dana tidak cukup",
            mt5.TRADE_RETCODE_TRADE_DISABLED: "Trading dinonaktifkan oleh broker",
            mt5.TRADE_RETCODE_CLIENT_DISABLES_AT: "Algo Trading dimatikan di terminal",
        }
        msg = fatal_map.get(rc, result.comment)
        return OrderResult(False, 0, rc, f"{msg} (retcode {rc})", 0.0)

    # ------------------------------------------------------------------
    # ORDER: ubah SL
    # ------------------------------------------------------------------
    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        """
        Ubah SL posisi ke new_sl menggunakan TRADE_ACTION_SLTP.
        Kembalikan True jika berhasil.
        """
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]

        sym_info = mt5.symbol_info(p.symbol)
        if sym_info is None:
            return False
        digits = sym_info.digits
        new_sl_r = round(new_sl, digits)

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": p.symbol,
            "sl": new_sl_r,
            "tp": p.tp,
            "magic": BOT_MAGIC,
            "comment": "bot-xau-trail",
        }
        result = mt5.order_send(request)
        if result is None:
            return False
        return result.retcode == mt5.TRADE_RETCODE_DONE

    # ------------------------------------------------------------------
    # ORDER: tutup posisi
    # ------------------------------------------------------------------
    def close_position(self, ticket: int) -> bool:
        """
        Tutup posisi berdasarkan ticket. Digunakan untuk penutupan darurat.
        Kembalikan True jika berhasil.
        """
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]

        sym_info = mt5.symbol_info(p.symbol)
        if sym_info is None:
            return False

        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            return False

        # Tutup di arah berlawanan
        if p.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = float(tick.bid)
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = float(tick.ask)

        filling = self._get_filling_mode(sym_info)
        deviation = getattr(self.cfg, "max_slippage_points", 30)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": order_type,
            "price": price,
            "deviation": deviation,
            "magic": BOT_MAGIC,
            "comment": "bot-xau-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        result = mt5.order_send(request)
        if result is None:
            return False
        return result.retcode == mt5.TRADE_RETCODE_DONE

    # ------------------------------------------------------------------
    # BACA: posisi terbuka milik bot
    # ------------------------------------------------------------------
    def get_bot_positions(self) -> List[PositionInfo]:
        """Kembalikan semua posisi terbuka dengan magic BOT_MAGIC."""
        positions = mt5.positions_get(symbol=self.cfg.symbol)
        if positions is None:
            return []
        result = []
        for p in positions:
            if p.magic != BOT_MAGIC:
                continue
            side = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
            result.append(PositionInfo(
                ticket=p.ticket,
                side=side,
                symbol=p.symbol,
                volume=p.volume,
                entry_price=float(p.price_open),
                sl=float(p.sl),
                open_time=pd.to_datetime(p.time, unit="s"),
            ))
        return result

    # ------------------------------------------------------------------
    # BACA: riwayat deal per position id
    # ------------------------------------------------------------------
    def get_position_deals(self, position_id: int) -> List[DealInfo]:
        """
        Ambil semua deal untuk position_id tertentu.
        Mencakup deal entry dan exit.
        """
        import datetime
        # Rentang waktu lebar: 30 hari ke belakang sampai 1 hari ke depan
        time_from = datetime.datetime.now() - datetime.timedelta(days=30)
        time_to = datetime.datetime.now() + datetime.timedelta(days=1)
        deals = mt5.history_deals_get(time_from, time_to)
        if deals is None:
            return []

        result = []
        for d in deals:
            if d.position_id != position_id:
                continue
            side = 1 if d.type == mt5.DEAL_TYPE_BUY else -1
            result.append(DealInfo(
                ticket=d.ticket,
                position_id=d.position_id,
                side=side,
                price=float(d.price),
                volume=float(d.volume),
                profit=float(d.profit),
                commission=float(d.commission),
                swap=float(d.swap),
                time=pd.to_datetime(d.time, unit="s"),
                comment=str(d.comment),
                reason=int(d.reason),
            ))
        return result
