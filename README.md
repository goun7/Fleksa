# Fleksa — Otonom Enerji Esnekliği & Dağıtık Batarya Arbitraj Motoru

> **Ana-belge:** [`FLEKSA.md`](FLEKSA.md) — v16.0 kapsamlı-master-spec
> ( OpenADR-2.0b/3.0, IEEE-2030.5, IPMVP, ISO-50001, EPDK-yan-hizmetler).
> **Bu-README-hızlı-başlangıç-içindir; ayrıntılar-ana-belgede.**

## Rolü ( TAMGA-MESH-içinde)

Fleksa **fon yönetmez** — **enerji-esnekliği-kanıtı** üretir: bir talep-
yanıtı-kararının gerçekten-yürütüldüğünü ve ölçülebildiğini kaydeder.

```
grid-sinyali → MPC-çekirdeği ( HiGHS) → dispatch-kararı
        ↓ ( her-adımda-ölçüm-kanıtı)
   IPMVP-M&V-stüdyosu → Merkle-kanıt → §6-foreign_chain_proof
        ↓
   tamga D5-ledger ( RFC-010 §6: fleksa-zinciri-kendi-adında)
```

## Kardeş-sınırı ( egemenlik)

Fleksa %100-egemendir; **hiçbir-kardeşe-zorunlu-bağımlılık-yok**:
`63-Sester` ( ödeme), `68-Kredent` ( kimlik), `69-Swarmax` ( filo),
`73-Veridrome` ( sertifika), `77-Dümen` ( iç-denetim).

## Güvenlik-modeli ( AT-141..161-§6-dikişleri)

| Özellik | Uygulama |
|---|---|
| §6-head | Merkle-ağacı-kökü; `evidence_link`-ile-receiptHash'e-bağlı |
| Kanıt-adı | `fleksa`-kendi-adında ( AT-107/134-dersi) |
| Flex-Policy-v2 | egemen-stüdyo; dış-politikaya-bağımlı-DEĞİL |
| Teorem-1 | arbitraj-kapısı ( matematiksel-kanıt) |

## Sınırlar ( dürüst)

- ** Enerji-erişimi-YOK** — bu-bir-karar-motorudur; gerçek-grid-erişimi
  OpenADR/Modbus-entegrasyonları-üzerinden-istenir ( üretim-dağıtımı-öncesi)
- ** Kanıt-üretimi-fleksa-içindedir**; mesh-düzeyinde-mutabakat RFC-010'da
