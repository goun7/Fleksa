"""fleksa MCP sunucu testleri — Model Context Protocol 2025-06-18 over stdio.

JSON-RPC el sıkışması + 4 aracı (anchor_verify/ledger_head/anchor_replay/
audit_summary) uçtan-uca SUBPROCESS üzerinden çalıştırır. swarmax MCP
testlerinin aynı deseni ( stdio'yu besle, stdout JSON satırlarını çöz).

Sözleşmeler-tespit-edilenler:
  - initialize → protocolVersion + capabilities + serverInfo
  - tools/list → 4 aracın-da listesi
  - araç çağrısı → {"content":[{"type":"text","text":JSON}]}, asla exception
  - bozuk-zincir → ok=false RED ( fail-closed, traceback yok)
  - bilinmeyen-arac → JSON-RPC -32601 hatası
  - numpy çıktısı bile seri_leşebilmeli ( _jsonable son-kapısı)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server.py"
PROTOCOL_VERSION = "2025-06-18"


def _rpc(lines, env_extra=None, timeout=120):
    """Server'ı stdio üzerinden besle; yanıt satırlarını dict listesi dön."""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    reqs = list(lines or [])
    proc = subprocess.run(
        [sys.executable, str(SERVER)], input="\n".join(reqs) + "\n",
        capture_output=True, text=True, env=env, timeout=timeout,
        cwd=str(ROOT), check=False)
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return proc, out


def _init_line():
    return ('{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
            '{"protocolVersion":"2025-06-18","capabilities":{},'
            '"clientInfo":{"name":"fleksa-mcp-test","version":"0.1"}}}')


def _tools_list():
    return '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'


def _call(req_id, name, arguments):
    return (f'{{"jsonrpc":"2.0","id":{req_id},"method":"tools/call",'
            f'"params":{{"name":"{name}",'
            f'"arguments":{json.dumps(arguments, ensure_ascii=False)}}}}}')


def _result_of(out, req_id):
    """tools/call veya rpc sonucunu çek → dict."""
    for d in out:
        if d.get("id") == req_id and "result" in d:
            return d["result"]
    return None


def _call_result(out, req_id):
    """tools/call yanıtını çek → {"content":[{"type":"text","text":JSON}]}."""
    for d in out:
        if d.get("id") == req_id and "result" in d:
            content = d["result"].get("content") or []
            if content:
                try:
                    return json.loads(content[0].get("text", ""))
                except json.JSONDecodeError:
                    return None
    return None


# ------------------------------------------------------------------ fixtures

@pytest.fixture()
def tamga_ledger(tmp_path) -> str:
    """Bilinen-iyi bir Tamga anchor ledger'ı — `fleksa tamga-anchor`'ın
    ürettiği formatta (tamga-sim/1 JSONL), doğrudan Python-API ile kurulur."""
    sys.path.insert(0, str(ROOT / "src"))
    from fleksa.audit.tamga_anchor import (
        OlcumTamgaSabitleyici,
        olcum_kanit_uret,
    )
    sabitleyici = OlcumTamgaSabitleyici()
    for h in [17, 18, 19, 20]:
        sabitleyici.sabitle(olcum_kanit_uret(
            tesis_id="tr-ist-eqx-02", olay="DR_PEAK_SHAVE",
            olay_id="evt-20261005-peak-01", saat=h,
            baseline_kw=320.0 - h, actual_kw=220.0 - h, tarif_try_kwh=3.80,
        ))
    sabitleyici.sabitle({"event": "DR_PEAK_SHAVE", "savings": {"kwh": 400.0}})
    assert sabitleyici.dogrula()
    yol = tmp_path / "tamga_ledger.jsonl"
    sabitleyici.tamga.jsonl_yaz(yol)
    return str(yol)


@pytest.fixture()
def broken_ledger(tamga_ledger, tmp_path) -> str:
    """Zinciri-sonradan-boz: ikinci kaydın ``h``'sini yeniden-hesapla ve
    BEKLENEN-değer olarak geri yaz — seq/prev geçerli kalır, ama ``h`` bir
    daha asla eşleşmez (kayıtlı prev/h kurcalanmış). Sonuç: ``yukle`` RED."""
    yol = tmp_path / "tamga_ledger_kirik.jsonl"
    kayitlar = [json.loads(l) for l in
                Path(tamga_ledger).read_text(encoding="utf-8").splitlines() if l.strip()]
    # kurcalanmış-kayıt: aynı payload, ama h değeri SELECTED-yanlış
    kayitlar[2]["h"] = "f" * 64
    with open(yol, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(rec, ensure_ascii=False) + "\n" for rec in kayitlar)
    return str(yol)


@pytest.fixture()
def ipmvp_inputs() -> dict:
    """`fleksa audit`'in deterministik senaryosunun GİRDİLERİ (sabit-tohum-123)
    — replays'in bağımsız-yeniden-türetme testi için."""
    sys.path.insert(0, str(ROOT / "src"))
    from fleksa.cli.main import _ipmvp_audit_scenario
    scn = _ipmvp_audit_scenario(5)
    return {
        "history": [list(map(float, day)) for day in scn["history"]],
        "actual": [float(x) for x in scn["actual"]],
        "ptf": [float(x) for x in scn["ptf"]],
        "event_hours": scn["event_hours"],
        "event_start_hour": scn["event_start_hour"],
        "expected_savings": scn["savings"],
        "expected_merkle_root": scn["audit_merkle_root"],
    }


# ------------------------------------------------------------------ protocol

def test_initialize_handshake():
    proc, out = _rpc([_init_line()])
    assert proc.returncode == 0
    r = _result_of(out, 1)
    assert r is not None
    assert r["protocolVersion"] == PROTOCOL_VERSION
    assert r["capabilities"] == {"tools": {"listChanged": False}}
    assert r["serverInfo"]["name"] == "fleksa"


def test_tools_list_four_tools():
    _, out = _rpc([_init_line(), _tools_list()])
    r = _result_of(out, 2)
    names = {t["name"] for t in r["tools"]}
    assert names == {"anchor_verify", "ledger_head", "anchor_replay",
                     "audit_summary"}
    # her aracın bir şeması ve açıklaması olmalı
    for t in r["tools"]:
        assert t["description"]
        assert isinstance(t["inputSchema"], dict)


def test_notifications_initialized_no_reply():
    """notifications/initialized bir BİLDİRİM — yanıt üretmemeli."""
    _, out = _rpc([
        _init_line(),
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":7,"method":"ping","params":{}}'])
    # sadece init+ping Yanıtlanmalı — 2 yanıt, 3 değil
    ids = [d["id"] for d in out if "result" in d or "error" in d]
    assert 7 in ids
    assert len(ids) == 2


# ------------------------------------------------------------------ anchor_verify

def test_anchor_verify_known_good_ledger(tamga_ledger):
    _, out = _rpc([_init_line(),
                   _call(3, "anchor_verify", {"ledger_path": tamga_ledger})])
    res = _call_result(out, 3)
    assert res["ok"] is True
    assert res["entries"] == 5
    assert res["olcum_sayisi"] == 5
    assert len(res["tamga_tip"]) == 64  # sha256-hex zincir-head'i
    assert res["merkle_kok"]


def test_anchor_verify_missing_file_is_red_not_crash():
    _, out = _rpc([_init_line(),
                   _call(3, "anchor_verify",
                         {"ledger_path": "/yok/boyle/bir/dizin/ledger.jsonl"})])
    res = _call_result(out, 3)
    assert res["ok"] is False
    assert "ledger-okunamadi" in res["reason"]
    # asla traceback — JSON kanıtı geldi
    assert "Traceback" not in json.dumps(res)


def test_anchor_verify_tampered_ledger_is_red(broken_ledger):
    """Kurcalanmış-zincir: ``h`` değeri değiştirildi — ``yukle`` fail-closed
    RED döner (zincir-gecersiz), asla traceback."""
    _, out = _rpc([_init_line(),
                   _call(3, "anchor_verify", {"ledger_path": broken_ledger})])
    res = _call_result(out, 3)
    assert res["ok"] is False
    assert "zincir-gecersiz" in res["reason"]
    assert "Traceback" not in json.dumps(res)


def test_anchor_verify_missing_arg_is_red():
    _, out = _rpc([_init_line(), _call(3, "anchor_verify", {})])
    res = _call_result(out, 3)
    assert res["ok"] is False
    assert "ledger_path-zorunlu" in res["reason"]


# ------------------------------------------------------------------ ledger_head

def test_ledger_head_known_good(tamga_ledger):
    _, out = _rpc([_init_line(),
                   _call(4, "ledger_head", {"ledger_path": tamga_ledger})])
    res = _call_result(out, 4)
    assert res["ok"] is True
    assert len(res["head"]) == 64
    assert res["entries"] == 5


def test_ledger_head_empty_file_is_red(tmp_path):
    yol = tmp_path / "bos.jsonl"
    yol.write_text("", encoding="utf-8")
    _, out = _rpc([_init_line(),
                   _call(4, "ledger_head", {"ledger_path": str(yol)})])
    res = _call_result(out, 4)
    assert res["ok"] is False
    assert "ledger-bos" in res["reason"]


# ------------------------------------------------------------------ anchor_replay

def test_anchor_replay_independent_rederivation(ipmvp_inputs):
    """Kayıtlı girdilerden bağımsız-yeniden-türetme: expected_savings ile
    WORST-CASE karşılaştırması dahil — uyuşma GREEN."""
    _, out = _rpc([_init_line(),
                   _call(5, "anchor_replay", ipmvp_inputs)])
    res = _call_result(out, 5)
    assert res["ok"] is True
    assert res["savings"]["net_curtailed_kwh"] == pytest.approx(
        ipmvp_inputs["expected_savings"]["net_curtailed_kwh"])
    assert res["ashrae_compliance"]["is_ashrae_compliant"] is True
    # numpy dizisinden gelen liste bile seri_leşti ( _jsonable)
    assert len(res["adjusted_baseline_kw"]) == 24


def test_anchor_replay_mismatched_claim_is_red(ipmvp_inputs):
    """İddia ile bağımsız-yeniden-türetme uyuşmazsa — fail-closed RED."""
    girdi = dict(ipmvp_inputs)
    girdi["expected_savings"] = dict(ipmvp_inputs["expected_savings"])
    girdi["expected_savings"]["net_curtailed_kwh"] = 0.0
    _, out = _rpc([_init_line(), _call(5, "anchor_replay", girdi)])
    res = _call_result(out, 5)
    assert res["ok"] is False
    assert "replay-uyumsuz" in res["reason"]


def test_anchor_replay_missing_inputs_is_red():
    _, out = _rpc([_init_line(), _call(5, "anchor_replay", {"history": []})])
    res = _call_result(out, 5)
    assert res["ok"] is False
    assert "history-ve-actual-zorunlu" in res["reason"]


# ------------------------------------------------------------------ audit_summary

def test_audit_summary_deterministic_mnv():
    _, out = _rpc([_init_line(), _call(6, "audit_summary", {})])
    res = _call_result(out, 6)
    assert res["ok"] is True
    assert res["event_hours"] == [17, 18, 19, 20]
    assert res["savings"]["net_curtailed_kwh"] == pytest.approx(399.21)
    assert res["ashrae_compliance"]["is_ashrae_compliant"] is True
    assert len(res["audit_merkle_root"]) == 64
    assert "IPMVP_Option_B" in res["standards"]


def test_audit_summary_invalid_history_days_is_red():
    _, out = _rpc([_init_line(),
                   _call(6, "audit_summary", {"history_days": 2})])
    res = _call_result(out, 6)
    assert res["ok"] is False
    assert "audit-senaryo-hatasi" in res["reason"]
    assert "Traceback" not in json.dumps(res)


# ------------------------------------------------------------------ hata-yolları

def test_unknown_tool_jsonrpc_error():
    _, out = _rpc([_init_line(),
                   _call(7, "yok-boyle-arac", {})])
    errs = [d for d in out if d.get("id") == 7 and "error" in d]
    assert errs
    assert errs[0]["error"]["code"] == -32601
    assert "bilinmeyen-arac" in errs[0]["error"]["message"]


def test_invalid_json_does_not_crash():
    _, out = _rpc(["bu-bir-json-degil",
                   _init_line(),
                   '{"jsonrpc":"2.0","id":9,"method":"ping","params":{}}'])
    # ping hâlâ yanıtlanmalı — sunucu ayakta
    ids = [d["id"] for d in out if "result" in d or "error" in d]
    assert 9 in ids


# ------------------------------------------------- G24-README-test-sayisi-pini

def test_readme_test_count_is_not_stale():
    """G24-pini: README'nin test-sayisi iddia-sayisi gercek-collect'e esit.
    Eski-641-olgusu: G13-MCP-commiti 16-yeni-test ekledi ama README'deki
    sayi-guncellenmedi - stale-iddia, olcum-tarafindan-yakalanmali."""
    import re as _re
    import subprocess as _sub
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = _re.search(r"Testleri [^\n]*\(\s*(\d+)\s*test", readme)
    assert m, "README test-sayisi-satiri-bulunamadi"
    claimed = int(m.group(1))
    res = _sub.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert res.returncode == 0, res.stderr[-400:]
    num = None
    for ln in res.stdout.splitlines():
        mm = _re.search(r"(\d+) tests? collected", ln)
        if mm:
            num = int(mm.group(1))
    assert num is not None, "collect-total-ayristirilamadi: %r" % res.stdout[-300:]
    assert num == claimed, (
        "README-stale-test-sayisi: iddia=%d gercek=%d" % (claimed, num))
