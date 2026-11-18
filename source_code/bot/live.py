"""
live.py - Loop utama bot trading live (Tahap 4).

Alur (sesuai AGENT_BRIEF 3.8):
  start -> rekonsiliasi posisi terbuka -> baca state -> tampilkan data -> menu
  -> loop:
       deteksi candle M1 baru tutup
       -> hitung sinyal (>= 1500 candle tutup)
       -> filter (spread, jam, terkunci, 1 posisi, drawdown, daily loss)
       -> entry buy/sell + SL (1R)
       -> pantau tiap 1-2 detik
       -> trailing (geser SL di server)
       -> deteksi tutup (riwayat deal) -> label -> catat CSV -> perbarui state

MODE=signal_only (default): tampilkan sinyal tanpa order.
MODE=demo_orders: kirim order, hanya akun DEMO.

KEAMANAN:
  - Akun REAL ditolak kecuali ALLOW_REAL=true (tidak pernah di-set oleh agent).
  - Kill switch: jika file data/STOP ada, tidak ada entry baru.
  - Satu posisi bot sekali waktu.
"""
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import Config
from .logger import log_trade_csv, setup_logger
from .risk import (
    LossLock,
    check_daily_loss,
    check_drawdown,
    check_spread_filter,
    in_trading_hours,
)
from .state import BotState, load_state, save_state
from .strategy import StrategyParams, generate_signals
from .trailing import calculate_trailing_stop

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent
STOP_FILE = BASE_DIR / "data" / "STOP"
STATE_PATH = BASE_DIR / "data" / "state.json"

# Jumlah candle minimum untuk hitung sinyal (candle tutup, tanpa candle berjalan)
MIN_CANDLES_FOR_SIGNAL = 1500
# Interval pantau posisi dalam detik
MONITOR_INTERVAL = 1.5
# Backoff reconnect
BACKOFF_BASE = 2.0
BACKOFF_MAX = 120.0

logger = logging.getLogger("bot_trade")


def _wib_date() -> date:
    """Tanggal hari ini di WIB (Asia/Jakarta)."""
    tz = ZoneInfo("Asia/Jakarta")
    return datetime.now(tz).date()


def _wib_now() -> datetime:
    """Waktu sekarang di WIB."""
    tz = ZoneInfo("Asia/Jakarta")
    return datetime.now(tz)


@dataclass
class ActivePosition:
    """Posisi live yang sedang dipantau bot."""
    ticket: int
    side: int           # 1=buy, -1=sell
    entry_price: float
    sl_initial: float   # SL awal (SL rugi = 1R)
    r: float            # jarak 1R dalam satuan harga
    current_sl: float
    trailing_level: int
    max_profit_r: float
    entry_time: datetime
    spread_at_entry: int


def _compute_profit_r(side: int, entry: float, r: float,
                      bid: float, ask: float) -> float:
    """
    Profit berjalan dalam R.
    Buy: pakai bid (jual). Sell: pakai ask (tutup sell).
    """
    if r <= 0:
        return 0.0
    if side == 1:
        return (bid - entry) / r
    else:
        return (entry - ask) / r


def _make_strategy_params(cfg: Config) -> StrategyParams:
    return StrategyParams(
        ema_fast=cfg.ema_fast,
        ema_slow=cfg.ema_slow,
        adx_min=cfg.adx_min,
        rsi_period=cfg.rsi_period,
        atr_mult=cfg.atr_mult,
    )


class LiveBot:
    """
    Komponen bot trading live.
    Dapat diuji dengan fake_mt5 (tes tidak butuh MT5 asli).
    """

    def __init__(self, cfg: Config, client, state: Optional[BotState] = None):
        """
        cfg: Config dari load_config()
        client: MT5Client (atau fake untuk tes)
        state: BotState yang sudah dimuat (opsional, dibaca dari file jika None)
        """
        self.cfg = cfg
        self.client = client
        self.state = state or load_state(STATE_PATH)
        self.lock = LossLock(max_consecutive_loss=cfg.max_consecutive_loss)
        # Sinkronkan LossLock dari state tersimpan
        self._sync_lock_from_state()

        self.active_pos: Optional[ActivePosition] = None
        self.peak_equity: float = 0.0
        self.daily_loss_usd: float = 0.0
        self._last_candle_time: Optional[pd.Timestamp] = None
        self._reconciled: bool = False

        self.params = _make_strategy_params(cfg)
        setup_logger()

    def _sync_lock_from_state(self) -> None:
        """Sinkronkan state LossLock dari BotState yang dimuat."""
        from .risk import LossLockState
        self.lock.state.consecutive_losses = self.state.consecutive_losses
        if self.state.locked_date:
            try:
                self.lock.state.locked_date = date.fromisoformat(self.state.locked_date)
            except (ValueError, TypeError):
                self.lock.state.locked_date = None
        self.lock.state.override_active = self.state.override_active

    def _save_state(self) -> None:
        """Simpan state ke file."""
        self.state.consecutive_losses = self.lock.state.consecutive_losses
        ld = self.lock.state.locked_date
        self.state.locked_date = ld.isoformat() if ld else None
        self.state.override_active = self.lock.state.override_active
        self.state.last_update = _wib_now().isoformat()
        save_state(self.state, STATE_PATH)

    # ------------------------------------------------------------------
    # Rekonsiliasi posisi terbuka saat start
    # ------------------------------------------------------------------
    def reconcile(self) -> None:
        """
        Periksa posisi terbuka dengan magic bot.
        Jika ada: lanjutkan trailing dari SL yang terpasang di server.
        Blokir entry baru sampai rekonsiliasi selesai.
        """
        logger.info("[HEARTBEAT] Memulai rekonsiliasi posisi...")
        positions = self.client.get_bot_positions()

        if not positions:
            logger.info("Rekonsiliasi: tidak ada posisi terbuka.")
            self._reconciled = True
            return

        if len(positions) > 1:
            logger.warning(
                f"Rekonsiliasi: ditemukan {len(positions)} posisi bot. "
                "Hanya posisi pertama yang dilanjutkan; sisanya diabaikan (tidak ditutup)."
            )

        p = positions[0]
        # Hitung R dari state.json jika tersedia
        saved = self.state.open_position
        if saved and saved.get("ticket") == p.ticket:
            r = float(saved.get("r", 0.0))
            trailing_level = int(saved.get("trailing_level", 0))
        else:
            # Estimasi R dari SL yang terpasang di server
            r = abs(p.entry_price - p.sl)
            trailing_level = 0
            logger.warning(
                f"Rekonsiliasi: posisi {p.ticket} tidak ada di state.json. "
                f"R diperkirakan dari SL server: {r:.2f}"
            )

        if r <= 0:
            logger.warning("Rekonsiliasi: R = 0, tidak bisa melanjutkan trailing.")
            self._reconciled = True
            return

        self.active_pos = ActivePosition(
            ticket=p.ticket,
            side=p.side,
            entry_price=p.entry_price,
            sl_initial=p.entry_price - p.side * r,
            r=r,
            current_sl=p.sl,
            trailing_level=trailing_level,
            max_profit_r=0.0,
            entry_time=p.open_time.to_pydatetime() if hasattr(p.open_time, "to_pydatetime") else datetime.now(),
            spread_at_entry=0,
        )
        logger.info(
            f"Rekonsiliasi: lanjutkan posisi {p.ticket} "
            f"{'BUY' if p.side == 1 else 'SELL'} "
            f"entry={p.entry_price:.2f} SL={p.sl:.2f} R={r:.2f}"
        )
        self._reconciled = True

    # ------------------------------------------------------------------
    # Deteksi candle baru tutup
    # ------------------------------------------------------------------
    def _get_closed_candles(self, count: int = MIN_CANDLES_FOR_SIGNAL + 2) -> pd.DataFrame:
        """
        Ambil candle M1. Buang candle berjalan (candle terakhir = masih buka).
        Kembalikan hanya candle tutup.
        """
        df = self.client.get_candles(count)
        if df.empty or len(df) < 2:
            return pd.DataFrame()
        return df.iloc[:-1].copy()  # buang candle terakhir (sedang berjalan)

    def _is_new_candle(self, closed: pd.DataFrame) -> bool:
        """True jika ada candle tutup baru sejak iterasi terakhir."""
        if closed.empty:
            return False
        last_time = closed.iloc[-1]["time"]
        if self._last_candle_time is None or last_time != self._last_candle_time:
            self._last_candle_time = last_time
            return True
        return False

    # ------------------------------------------------------------------
    # Pantau posisi aktif
    # ------------------------------------------------------------------
    def _monitor_position(self) -> Optional[dict]:
        """
        Pantau posisi aktif: perbarui trailing, cek penutupan.
        Kembalikan dict hasil trade jika posisi sudah ditutup, atau None.
        """
        if self.active_pos is None:
            return None

        pos = self.active_pos
        tick = None
        try:
            sym = self.client.get_symbol()
            tick_bid = sym.bid
            tick_ask = sym.ask
        except Exception:
            return None  # MT5 error sementara, coba lagi

        if tick_bid == 0:
            return None  # Pasar tutup / tick basi

        # Cek apakah posisi masih terbuka
        bot_positions = self.client.get_bot_positions()
        still_open = any(p.ticket == pos.ticket for p in bot_positions)

        if not still_open:
            # Posisi sudah ditutup (kena SL atau sebab lain)
            result = self._handle_position_closed(pos, tick_bid, tick_ask)
            self.active_pos = None
            self.state.open_position = None
            return result

        # Update trailing
        profit_r = _compute_profit_r(pos.side, pos.entry_price, pos.r, tick_bid, tick_ask)
        pos.max_profit_r = max(pos.max_profit_r, profit_r)

        new_level, new_sl = calculate_trailing_stop(
            side=pos.side,
            entry=pos.entry_price,
            r=pos.r,
            fav_profit_r=pos.max_profit_r,
            current_level=pos.trailing_level,
            current_sl=pos.current_sl,
        )

        if new_level > pos.trailing_level or abs(new_sl - pos.current_sl) > 1e-6:
            # SL bergeser - kirim ke server
            if pos.side == 1:
                should_move = new_sl > pos.current_sl
            else:
                should_move = new_sl < pos.current_sl

            if should_move:
                ok = self.client.modify_sl(pos.ticket, new_sl)
                if ok:
                    logger.info(
                        f"Trailing: SL digeser dari {pos.current_sl:.2f} ke {new_sl:.2f} "
                        f"(level {pos.trailing_level} -> {new_level})"
                    )
                    pos.current_sl = new_sl
                    pos.trailing_level = new_level
                    # Perbarui state.open_position
                    self.state.open_position = {
                        "ticket": pos.ticket,
                        "side": pos.side,
                        "entry_price": pos.entry_price,
                        "r": pos.r,
                        "current_sl": pos.current_sl,
                        "trailing_level": pos.trailing_level,
                    }
                    self._save_state()
                else:
                    logger.warning(f"Trailing: gagal menggeser SL untuk tiket {pos.ticket}")

        return None

    def _handle_position_closed(self, pos: ActivePosition,
                                 final_bid: float, final_ask: float) -> dict:
        """Tangani posisi yang sudah tertutup. Kembalikan dict hasil trade."""
        # Ambil riwayat deal
        deals = self.client.get_position_deals(pos.ticket)
        exit_deal = None
        for d in sorted(deals, key=lambda x: x.time):
            # Deal keluar = arah berlawanan dari posisi
            if d.ticket != pos.ticket and d.position_id == pos.ticket:
                if (pos.side == 1 and d.side == -1) or (pos.side == -1 and d.side == 1):
                    exit_deal = d
                    break

        # Fallback jika deal tidak ditemukan
        if exit_deal is not None:
            exit_price = exit_deal.price
            profit_usd = exit_deal.profit + exit_deal.commission + exit_deal.swap
            exit_reason = exit_deal.reason
        else:
            exit_price = final_bid if pos.side == 1 else final_ask
            profit_usd = (exit_price - pos.entry_price) * pos.side * self.cfg.lot_size * 100.0
            exit_reason = -1
            logger.warning(f"Posisi {pos.ticket} ditutup tapi deal tidak ditemukan.")

        # Hitung pnl_r
        pnl_r = (exit_price - pos.entry_price) * pos.side / pos.r if pos.r > 0 else 0.0

        # Label
        # DEAL_REASON_SL=0, DEAL_REASON_STOPOUT=1 (MT5)
        SL_REASONS = {0, 1}
        if exit_deal is None:
            # Fallback: level 0 = SL rugi, >0 = SL profitN
            label = "SL rugi" if pos.trailing_level == 0 else f"SL profit{pos.trailing_level}"
        elif exit_reason in SL_REASONS:
            # Ditutup karena SL server
            label = "SL rugi" if pos.trailing_level == 0 else f"SL profit{pos.trailing_level}"
        else:
            # Ditutup bukan karena SL (manual, TP, dll)
            label = "LAIN"

        # Slippage (selisih harga eksekusi vs SL yang terpasang)
        if pos.trailing_level == 0:
            expected_exit = pos.sl_initial
        else:
            expected_exit = pos.current_sl
        slippage = abs(exit_price - expected_exit) / pos.r if pos.r > 0 else 0.0

        # Update state pengunci
        trade_date = _wib_date()
        is_loss = (label == "SL rugi")
        is_locked = self.lock.record_trade_result(is_loss, trade_date)
        if is_locked:
            logger.warning(
                f"PENGUNCI AKTIF: {self.lock.state.consecutive_losses} SL rugi berturut-turut "
                f"pada {trade_date}. Bot berhenti entry baru hari ini."
            )

        result = {
            "entry_time": pos.entry_time.isoformat(),
            "exit_time": datetime.now().isoformat(),
            "side": "BUY" if pos.side == 1 else "SELL",
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "label": label,
            "level": pos.trailing_level,
            "pnl_r": round(pnl_r, 3),
            "pnl_usd": round(profit_usd, 2),
            "spread_points": pos.spread_at_entry,
            "slippage": round(slippage, 3),
        }
        log_trade_csv(result)
        self._save_state()
        logger.info(
            f"Trade selesai: {label} | {result['side']} "
            f"entry={pos.entry_price:.2f} exit={exit_price:.2f} "
            f"pnl={pnl_r:+.2f}R ({profit_usd:+.2f} USD)"
        )
        return result

    # ------------------------------------------------------------------
    # Entry posisi baru
    # ------------------------------------------------------------------
    def _attempt_entry(self, signal: int, sl_distance: float,
                       spread_points: int) -> None:
        """
        Coba entry baru jika semua filter lolos.
        signal: 1=buy, -1=sell
        sl_distance: jarak SL (1R) dari sinyal ATR
        """
        if self.active_pos is not None:
            return  # Sudah ada posisi

        if not self._reconciled:
            return  # Belum rekonsiliasi

        # Kill switch
        if STOP_FILE.exists():
            logger.info("Kill switch aktif (data/STOP ada). Tidak ada entry baru.")
            return

        # Cek terkunci
        today = _wib_date()
        if self.lock.is_locked(today):
            logger.info(f"Bot terkunci hari ini ({today}). Lewati sinyal.")
            return

        # Filter spread
        if not check_spread_filter(spread_points, self.cfg.max_spread):
            logger.info(f"Sinyal dilewati: spread {spread_points} > batas {self.cfg.max_spread}")
            return

        # Filter daily loss dan drawdown (opsional, default mati)
        # peak_equity diperbarui di loop utama
        if not check_daily_loss(self.daily_loss_usd, self.peak_equity, self.cfg.max_daily_loss_percent):
            logger.info("Sinyal dilewati: batas rugi harian tercapai.")
            return
        if not check_drawdown(self.peak_equity, self.peak_equity - self.daily_loss_usd,
                              self.cfg.max_drawdown_percent):
            logger.info("Sinyal dilewati: batas drawdown tercapai.")
            return

        side_name = "BUY" if signal == 1 else "SELL"

        # signal_only: tampilkan sinyal, tidak kirim order
        if self.cfg.mode == "signal_only":
            logger.info(
                f"[SINYAL] {side_name} | sl_distance={sl_distance:.2f} | spread={spread_points} poin "
                f"| MODE=signal_only: tidak ada order"
            )
            return

        # demo_orders: hanya akun DEMO
        # (validasi akun REAL sudah ada di mt5_client._validate_pre_order)
        logger.info(f"Entry {side_name} | sl_distance={sl_distance:.2f} | spread={spread_points}")
        result = self.client.send_market_order(signal, sl_distance)

        if not result.success:
            logger.warning(f"Order gagal: {result.comment} (retcode={result.retcode})")
            # Jika retriable: loop berikutnya bisa coba lagi
            return

        actual_entry = result.entry_price
        if actual_entry <= 0:
            # Fallback ke harga sinyal
            sym = self.client.get_symbol()
            actual_entry = sym.ask if signal == 1 else sym.bid

        sl_initial = actual_entry - signal * sl_distance

        self.active_pos = ActivePosition(
            ticket=result.ticket,
            side=signal,
            entry_price=actual_entry,
            sl_initial=sl_initial,
            r=sl_distance,
            current_sl=sl_initial,
            trailing_level=0,
            max_profit_r=0.0,
            entry_time=_wib_now(),
            spread_at_entry=spread_points,
        )
        self.state.open_position = {
            "ticket": result.ticket,
            "side": signal,
            "entry_price": actual_entry,
            "r": sl_distance,
            "current_sl": sl_initial,
            "trailing_level": 0,
        }
        self._save_state()
        logger.info(
            f"Order masuk: tiket={result.ticket} {side_name} "
            f"entry={actual_entry:.2f} SL={sl_initial:.2f} R={sl_distance:.2f}"
        )

    # ------------------------------------------------------------------
    # Loop utama
    # ------------------------------------------------------------------
    def run(self, max_iterations: Optional[int] = None) -> None:
        """
        Loop utama bot. Keluar dengan Ctrl+C atau max_iterations (untuk tes).
        """
        logger.info("[HEARTBEAT] Bot live dimulai.")
        self.reconcile()
        self._save_state()

        iterations = 0
        backoff = BACKOFF_BASE

        while True:
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1

            try:
                self._tick()
                backoff = BACKOFF_BASE  # reset setelah sukses
                time.sleep(MONITOR_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Bot dihentikan oleh pengguna (Ctrl+C).")
                break

            except Exception as exc:
                logger.error(f"Exception di loop utama: {exc}", exc_info=True)
                # Reconnect dengan exponential backoff
                wait = min(backoff, BACKOFF_MAX)
                logger.info(f"Reconnect dalam {wait:.1f} detik...")
                time.sleep(wait)
                backoff = min(backoff * 2, BACKOFF_MAX)
                try:
                    self.client.connect()
                    logger.info("[HEARTBEAT] Reconnect berhasil.")
                    backoff = BACKOFF_BASE
                except Exception as conn_err:
                    logger.error(f"Reconnect gagal: {conn_err}")

        logger.info("[HEARTBEAT] Bot live berhenti.")

    def _tick(self) -> None:
        """Satu iterasi loop: pantau posisi + cek sinyal baru."""
        # Pantau posisi aktif
        trade_result = self._monitor_position()
        if trade_result:
            # Posisi baru ditutup - bisa langsung cari sinyal baru di tick berikutnya
            pass

        # Update peak equity
        try:
            acc = self.client.get_account()
            if acc.equity > self.peak_equity:
                self.peak_equity = acc.equity
        except Exception:
            pass

        # Jika sudah ada posisi aktif, tidak perlu cari sinyal
        if self.active_pos is not None:
            return

        # Ambil candle tutup
        closed = self._get_closed_candles(MIN_CANDLES_FOR_SIGNAL + 2)
        if closed.empty or len(closed) < MIN_CANDLES_FOR_SIGNAL:
            return  # Data tidak cukup

        # Deteksi candle baru tutup
        if not self._is_new_candle(closed):
            return  # Tidak ada candle baru

        # Hitung sinyal
        try:
            df_sig = generate_signals(closed, self.params)
        except Exception as e:
            logger.error(f"generate_signals error: {e}")
            return

        last = df_sig.iloc[-1]
        signal = int(last["signal"])
        sl_distance = float(last["sl_distance"]) if "sl_distance" in last else 0.0

        if signal == 0 or sl_distance <= 0:
            return  # Tidak ada sinyal

        # Baca spread saat ini
        try:
            sym = self.client.get_symbol()
            spread_points = sym.spread_points
        except Exception:
            spread_points = 9999  # Konservatif: blokir jika tidak bisa baca

        self._attempt_entry(signal, sl_distance, spread_points)
