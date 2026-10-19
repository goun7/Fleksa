#!/usr/bin/env python3
"""fleksa MCP sunucusu — Model Context Protocol 2025-06-18 over stdio.

Fleksa enerji-esnekliği doğrulama çekirdeğini (IPMVP Option B /
EVO 10001-1:2022 / ASHRAE Guideline 14) AI ajanlarına MCP araçları
olarak sunar.

Tasarım-ilkesi (tamga/swarmax MCP sunucuları ile aynı sözleşme):
  • SAF STDLIB — hiçbir pip bağımliliği; sunucu tek-başına çalışır.
  • HİÇBİR ZAMAN exception — her araç JSON kanıtı döndürür; traceback
    DEĞİL "ok:false, reason:…" (tamga AT-192 message-RED disiplini).
    ``_jsonable`` + ``_text`` son-kapısı: numpy skaleri/dizileri veya
    sqlite3.Row gibi json.dumps'a-verilemeyen tipler bile güvenli şekilde
    JSON'a çevrilir (swarmax MCP'sinde gerçek bir çöküşe yol açan sınıf).
  • AĞIR-BAĞIMLILIK-İÇERDE-DEĞİL — ``from fleksa...`` importları HANDLER
    içindedir, modül-tepesinde DEĞİL: numpy/click eksik olsa bile sunucu
    başlar, yalnızca o araç RED döner.
  • SALT-OKUMA/DOĞRULAMA — bu sunucu ölçüm kanıtı ÜRETMEZ; mevcut
    Fleksa API'larını çağırır ve doğrular (ledger JSONL okuma,
    bağımsız yeniden-türetme, zincir denetimi).

Araçlar:
  anchor_verify      Tamga JSONL ledger'ı + Fleksa Merkle çapraz-çapasını doğrula
  anchor_replay      kayitli girdilerden M&V sonucunu bağımsız yeniden-türet
  audit_summary     deterministik IPMVP senaryosunun baseline/savings/ASHRAE özeti
  ledger_head        Tamga zincirinin geçerli head'ini döndür

Çalıştırma:
  python3 mcp/server.py                    # stdio JSON-RPC
  (istemci tarafı: "command": "python",
    "args": ["<repo>/mcp/server.py"])
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "fleksa"
SERVER_VERSION = "0.1.0"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": msg}}


def _jsonable(obj):
    """Herhangi bir değeri json.dumps'a-güvenli tipe indirger — özyineli.

    swarmax MCP'sinde REAL bir hataya yol açan sınıf burada da geçerlidir:
    Fleksa'nın M&V yolları ``numpy.float64``/``np.ndarray`` döndürür ve
    ``json.dumps`` bunları seri_leştiremez → sunucu traceback'le çöker.
    Row/numpy/Path/Decimal gibi mayinleri bu dönüşümsiz bırakmamak
    sözleşmenin (asla-exception) tamamlayıcısıdır.
    """
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    # sqlite3.Row (olası fleksa DB yolları) — keys() gereklidir, `in` değil
    try:
        import sqlite3
    except ImportError:  # pragma: no cover
        sqlite3 = None
    if sqlite3 is not None and isinstance(obj, sqlite3.Row):
        return {k: _jsonable(obj[k]) for k in obj.keys()}  # noqa: SIM118
    # numpy skaler/dizi — fleksa M&V'nin birincil çıktı tipi
    try:
        import numpy as _np
    except ImportError:  # pragma: no cover — numpy fleksa'da her zaman var
        _np = None
    if _np is not None:
        if isinstance(obj, _np.ndarray):
            return _jsonable(obj.tolist())
        if isinstance(obj, _np.generic):
            return _jsonable(obj.item())
    if isinstance(obj, float):
        return obj
    if isinstance(obj, (int, str)) or obj is None:
        return obj
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    # son-başvuru: bilinmeyen tipler dizeye — seri_leştirmeyi bloklama
    return str(obj)


def _text(payload: dict) -> dict:
    """Asla-exception sözleşmesinin-son-kapısı: serileştirme-başarısızlığı
    bile JSON kanıtı döndürür (tamga AT-192 message-RED disiplini)."""
    try:
        text = json.dumps(_jsonable(payload), ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 — son-kapı, traceback-YASAK
        text = json.dumps({"ok": False,
                           "reason": f"serilestirme-hatasi: {type(e).__name__}: {e}"})
    return {"content": [{"type": "text", "text": text}]}


# --- yardımcılar ---------------------------------------------------------------

def _ledger_kayitlari(path: str) -> list | None:
    """Tamga JSONL ledger'ını oku — hata → None DEĞİL, çağıran RED döner."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        kayitlar = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    kayitlar.append(json.loads(line))
        return kayitlar
    except Exception:  # noqa: BLE001 — JSON kanıtı üretilemedi, RED
        return None


def _anchor_dogrula(kayitlar: list) -> dict:
    """Tamga zinciri + Fleksa Merkle çapraz-çapasını doğrula (üç katman).

    OlcumTamgaSabitleyici.dogrula() ile AYNI kurallar, ancak kayıtlı
    (diskten-okunmuş) zincir üzerinden — sunucu ölçüm ÜRETMEZ.
    """
    from fleksa.audit.ledger import CryptographicSavingsLedger
    from fleksa.audit.tamga_anchor import (
        KAYIT_TIPI,
        KAYNAK_PROJE,
        TamgaLedger,
    )

    ledger = TamgaLedger()
    try:
        ledger.yukle(kayitlar)
    except Exception as e:  # noqa: BLE001 — BozukTamgaZinciriError dahil
        return {"ok": False, "reason": f"zincir-gecersiz: {e}"}

    if not ledger.verify():
        return {"ok": False, "reason": "zincir-dogrulamadi: seq/prev/h uyumsuz"}

    # çapraz-çapa + tamlık (dogrula'nın katman 2-3'ü — kayıtlı payload üzerinden)
    yeniden = CryptographicSavingsLedger()
    sayi = 0
    for rec in ledger.entries:
        if rec.get("tip") != KAYIT_TIPI or rec.get("kaynak") != KAYNAK_PROJE:
            continue
        yaprak = yeniden.append_entry(rec.get("payload", {}))
        if rec.get("olcum_yaprak") != yaprak:
            return {"ok": False, "reason": "olcum-kurcalanmis: yaprak-uyumsuz"}
        if rec.get("merkle_kok") != yeniden.compute_merkle_root():
            return {"ok": False, "reason": "merkle-kok-uyumsuz: geriye-donuk-degisiklik"}
        sayi += 1

    return {
        "ok": True,
        "entries": len(ledger),
        "olcum_sayisi": sayi,
        "tamga_tip": ledger.tip(),
        "merkle_kok": yeniden.compute_merkle_root() if yeniden.entries else None,
        "tamga_format": "tamga-sim/1",
    }


# --- araç implementasyonları ----------------------------------------------------

def _tool_anchor_verify(args: dict) -> dict:
    p = args.get("ledger_path")
    if not isinstance(p, str) or not p:
        return {"ok": False, "reason": "ledger_path-zorunlu (string)"}
    kayitlar = _ledger_kayitlari(p)
    if kayitlar is None:
        return {"ok": False, "reason": f"ledger-okunamadi: {p}"}
    if not kayitlar:
        return {"ok": False, "reason": f"ledger-bos: {p}"}
    try:
        return _anchor_dogrula(kayitlar)
    except Exception as e:  # noqa: BLE001 — cephedeki her hata JSON kanıtı
        return {"ok": False, "reason": f"anchor-dogrula-hatasi: {type(e).__name__}: {e}"}


def _tool_ledger_head(args: dict) -> dict:
    p = args.get("ledger_path")
    if not isinstance(p, str) or not p:
        return {"ok": False, "reason": "ledger_path-zorunlu (string)"}
    kayitlar = _ledger_kayitlari(p)
    if kayitlar is None:
        return {"ok": False, "reason": f"ledger-okunamadi: {p}"}
    if not kayitlar:
        return {"ok": False, "reason": f"ledger-bos: {p}"}
    try:
        from fleksa.audit.tamga_anchor import TamgaLedger
        ledger = TamgaLedger()
        ledger.yukle(kayitlar)
        if not ledger.verify():
            return {"ok": False, "reason": "zincir-gecersiz: head-türetilemez"}
        return {"ok": True, "head": ledger.tip(), "entries": len(ledger)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"ledger-head-hatasi: {type(e).__name__}: {e}"}


def _tool_anchor_replay(args: dict) -> dict:
    """Kayıtlı GİRDİLER'den M&V sonucunu bağımsız yeniden-türet ve karşı-laştır.

    `fleksa audit-verify` CLI'ının MCP cephesi: history/actual/ptf/event_hours
    over the recorded inputs tam sonucu yeniden hesaplar ve (verilmişse)
    beklenen savings/merkle-kökü ile karşılaştırır. Üretici-iddiası DEĞİL,
    bağımsız-yeniden-türetme döner.
    """
    history = args.get("history")
    actual = args.get("actual")
    if not isinstance(history, list) or not isinstance(actual, list):
        return {"ok": False,
                "reason": "history-ve-actual-zorunlu (24slik sayı-listeleri)"}
    event_hours = args.get("event_hours", [17, 18, 19, 20])
    if not isinstance(event_hours, list) or not event_hours:
        return {"ok": False, "reason": "event_hours-bos-degil (sayı-listesi)"}
    ptf = args.get("ptf")
    try:
        import numpy as np

        from fleksa.audit.baseline import IpmvpBaselineEngine
        from fleksa.audit.ledger import CryptographicSavingsLedger
    except Exception as e:  # noqa: BLE001 — ağır bağımlılık eksikse yine de başla
        return {"ok": False, "reason": f"bagimlilik-eksik: {type(e).__name__}: {e}"}

    try:
        baseline = IpmvpBaselineEngine.calculate_10_in_10_baseline(history)
        event_start = int(args.get("event_start_hour",
                                   min(event_hours)))
        pre = actual[max(0, event_start - 2):event_start]
        adjusted = IpmvpBaselineEngine.apply_same_day_adjustment(
            baseline_hourly_kw=baseline,
            pre_event_actual_2h_kw=pre,
            event_start_hour=event_start,
        )
        tariff = np.array(ptf if isinstance(ptf, list) else [3.80] * 24)
        savings = IpmvpBaselineEngine.compute_event_savings(
            adjusted_baseline_kw=adjusted,
            actual_meter_kw=np.array(actual),
            ptf_tariff_try_kwh=tariff,
            event_hours=event_hours,
        )
        ashrae = IpmvpBaselineEngine.evaluate_ashrae_compliance(
            actual=np.array(actual[:event_start]),
            baseline=adjusted[:event_start],
        )
        ledger = CryptographicSavingsLedger()
        ledger.append_entry({"event": "DR_PEAK_SHAVE", "savings": savings})
        kok = ledger.compute_merkle_root()
    except Exception as e:  # noqa: BLE001
        return {"ok": False,
                "reason": f"replay-hatasi: {type(e).__name__}: {e}"}

    sonuc: dict = {
        "ok": True,
        "savings": savings,
        "ashrae_compliance": ashrae,
        "merkle_kok": kok,
        "adjusted_baseline_kw": [round(float(x), 1) for x in adjusted],
    }
    # opsiyonel karşılaştırma — beklenen-iddia ile uyuşmazlık RED
    expected_savings = args.get("expected_savings")
    if isinstance(expected_savings, dict):
        for k in ("net_curtailed_kwh", "net_financial_savings_try"):
            if k in expected_savings and savings.get(k) != expected_savings[k]:
                return {"ok": False,
                        "reason": f"replay-uyumsuz: {k} beklenen "
                                  f"{expected_savings[k]!r}, yeniden {savings[k]!r}",
                        "savings": savings}
    expected_root = args.get("expected_merkle_root")
    if isinstance(expected_root, str) and expected_root != kok:
        return {"ok": False,
                "reason": f"replay-uyumsuz: merkle_kok beklenen "
                          f"{expected_root[:12]}…, yeniden {kok[:12]}…",
                "merkle_kok": kok}
    return sonuc


def _tool_audit_summary(args: dict) -> dict:
    """Deterministik IPMVP senaryosunun özetini verir (kayıtlı girdilerden).

    ``fleksa audit`` ile AYNI senaryoyu (sabit-tohum-123) yeniden-oynar:
    10-in-10 baseline, same-day-adjustment, event-savings ve ASHRAE
    Guideline 14 uyumunu döndürür.
    """
    try:
        import numpy as np  # noqa: F401 — _ipmvp_audit_scenario numpy kullanır

        from fleksa.cli.main import _ipmvp_audit_scenario
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"bagimlilik-eksik: {type(e).__name__}: {e}"}
    try:
        history_days = args.get("history_days", 5)
        if not isinstance(history_days, int) or history_days < 1:
            return {"ok": False, "reason": "history_days-pozitif-tamsayı-olmalı"}
        scn = _ipmvp_audit_scenario(history_days)
    except Exception as e:  # noqa: BLE001 — ValueError dahil her hata RED
        return {"ok": False, "reason": f"audit-senaryo-hatasi: {type(e).__name__}: {e}"}
    return {
        "ok": True,
        "history_days": history_days,
        "event_hours": scn["event_hours"],
        "event_start_hour": scn["event_start_hour"],
        "savings": scn["savings"],
        "ashrae_compliance": scn["ashrae"],
        "audit_merkle_root": scn["audit_merkle_root"],
        "standards": ["IPMVP_Option_B", "EVO_10001-1:2022",
                      "ASHRAE_Guideline_14"],
    }


TOOLS = {
    "anchor_verify": {
        "handler": _tool_anchor_verify,
        "description": (
            "Fleksa ölçüm-kanıtlarının sabitlendiği Tamga hash-zinciri "
            "JSONL ledger'ını bağımsız-doğrular: 1-based seq + prev-bağlantısı "
            "+ sha256(prev ‖ RFC-8785-JCS(kayıt)) VE her kayıtdaki Fleksa "
            "Merkle çapraz-çapasını (olcum_yaprak + merkle_kok) payload'dan "
            "yeniden-türetir. Salt-okuma — yeni kanıt ÜRETMEZ. "
            "Dönüş: {ok, entries, olcum_sayisi, tamga_tip, merkle_kok} "
            "— zincir/çapraz-çapa bozuksa ok=false RED."),
        "schema": {
            "type": "object",
            "properties": {
                "ledger_path": {
                    "type": "string",
                    "description": ("Tamga `tamga-sim/1` JSONL ledger yolu "
                                    "(fleksa tamga-anchor --ledger çıktısı)"),
                }},
            "required": ["ledger_path"],
        }},
    "ledger_head": {
        "handler": _tool_ledger_head,
        "description": (
            "Geçerli bir Tamga ledger'ın zincir-head'ini (son h, 64-hex) "
            "döndürür — başka bir sistemin çapası olarak. "
            "Dönüş: {ok, head, entries}"),
        "schema": {
            "type": "object",
            "properties": {
                "ledger_path": {"type": "string"},
            },
            "required": ["ledger_path"],
        }},
    "anchor_replay": {
        "handler": _tool_anchor_replay,
        "description": (
            "Kayıtlı GİRDİLER'den (history/actual/ptf/event_hours) IPMVP "
            "Option B M&V sonucunu BAĞIMSIZ yeniden-türetir: 10-in-10 "
            "baseline, same-day-adjustment, event-savings, ASHRAE Guideline "
            "14 istatistikleri ve Fleksa Merkle kökü. expected_savings / "
            "expected_merkle_root verilirse karşılaştırır — uyuşmazlık RED "
            "(fleksa audit-verify'ın MCP cephesi). "
            "Dönüş: {ok, savings, ashrae_compliance, merkle_kok, …}"),
        "schema": {
            "type": "object",
            "properties": {
                "history": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "benzer-geçmiş-günler (her biri 24 saatlik kW)",
                },
                "actual": {
                    "type": "array", "items": {"type": "number"},
                    "description": "olay-günü gerçek sayaç okuması (24 saatlik kW)",
                },
                "ptf": {
                    "type": "array", "items": {"type": "number"},
                    "description": "saatlik tarif (TL/kWh, opsiyonel — varsayılan 3.80)",
                },
                "event_hours": {
                    "type": "array", "items": {"type": "integer"},
                    "description": "DR olay-saatleri (varsayılan [17,18,19,20])",
                },
                "event_start_hour": {
                    "type": "integer",
                    "description": "olay başlangıç-saati (varsayılan min(event_hours))",
                },
                "expected_savings": {
                    "type": "object",
                    "description": "karşılaştırma-iddiası (opsiyonel)",
                },
                "expected_merkle_root": {
                    "type": "string",
                    "description": "karşılaştırma-iddiası (opsiyonel)",
                }},
            "required": ["history", "actual"],
        }},
    "audit_summary": {
        "handler": _tool_audit_summary,
        "description": (
            "Fleksa'nın deterministik IPMVP Option B / EVO 10001-1:2022 / "
            "ASHRAE Guideline 14 M&V senaryosunun özetini verir: event-hours, "
            "savings (kWh/TL), ASHRAE CV(RMSE)+NMBE uyumu ve Fleksa audit "
            "Merkle kökü. `fleksa audit` ile aynı sabit-tohum senaryosu. "
            "Dönüş: {ok, history_days, event_hours, savings, "
            "ashrae_compliance, audit_merkle_root, standards}"),
        "schema": {
            "type": "object",
            "properties": {
                "history_days": {
                    "type": "integer",
                    "description": "benzer-geçmiş-gün sayısı (varsayılan 5, min 3)",
                }},
            "required": [],
        }},
}


def _tools_list_result() -> dict:
    return {"tools": [
        {"name": name,
         "description": spec["description"],
         "inputSchema": spec["schema"]}
        for name, spec in TOOLS.items()]}


def _handle_call(req_id, params: dict) -> dict | None:
    name = params.get("name")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    spec = TOOLS.get(name)
    if spec is None:
        return _err(req_id, -32601, f"bilinmeyen-arac: {name}")
    try:
        payload = spec["handler"](args)
    except Exception as e:  # noqa: BLE001 — hiçbir yol exception'a düşmez
        payload = {"ok": False,
                   "reason": f"arac-ic-hata: {type(e).__name__}: {e}"}
    return _result(req_id, _text(payload))


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(_err(None, -32600, "gecersiz-json")) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(req, dict):
            sys.stdout.write(
                json.dumps(_err(None, -32600, "istek-bir-nesne-degil")) + "\n")
            sys.stdout.flush()
            continue
        method = req.get("method")
        req_id = req.get("id")
        if method == "initialize":
            sys.stdout.write(json.dumps(_result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "instructions": (
                        "Fleksa enerji-esnekliği doğrulama sunucusu "
                        "(salt-okuma/doğrulama). anchor_verify → Tamga zinciri "
                        "+ Merkle çapraz-çapası; ledger_head → zincir-ucu; "
                        "anchor_replay → kayıtlı girdilerden bağımsız "
                        "yeniden-türetme; audit_summary → IPMVP/ASHRAE özeti. "
                        "Her araç JSON kanıtı döner, asla exception fırlatmaz."),
                }})) + "\n")
        elif method == "notifications/initialized":
            continue  # bildirim — yanıt yok
        elif method == "tools/list":
            sys.stdout.write(
                json.dumps(_result(req_id, _tools_list_result())) + "\n")
        elif method == "tools/call":
            resp = _handle_call(req_id, req.get("params") or {})
            if resp is not None:
                sys.stdout.write(
                    json.dumps(resp, ensure_ascii=False) + "\n")
        elif method == "ping":
            sys.stdout.write(json.dumps(_result(req_id, {})) + "\n")
        elif req_id is not None:
            sys.stdout.write(json.dumps(_err(
                req_id, -32601, f"bilinmeyen-method: {method}")) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
