#!/usr/bin/env python3
# VALIDAZIONE COMPLETA DATASET 2020
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.model.identifiers import InstrumentId
from datetime import datetime
import time

print('=== VALIDAZIONE DATASET 2020 COMPLETO ===')

catalog_path = '/media/sam/2TB-NVMe/bybit_data_downloader/bybit_nautilus_2020_COMPLETE'
catalog = ParquetDataCatalog(catalog_path)
instrument_id = InstrumentId.from_str('BTCUSDT-LINEAR.BYBIT')

print(f'Catalog: {catalog_path}')
print(f'Instrument: {instrument_id}')

# Test accessibilità
start_time = time.time()
trade_ticks = catalog.trade_ticks([instrument_id])
load_time = time.time() - start_time

print(f'\n=== RISULTATI VALIDAZIONE ===')
print(f'⏱️  Tempo caricamento: {load_time:.2f} secondi')
print(f'📊 Trade ticks totali: {len(trade_ticks):,}')

if trade_ticks:
    # Validazione struttura dati
    first_tick = trade_ticks[0]
    last_tick = trade_ticks[-1]
    
    print(f'\n=== STRUTTURA DATI ===')
    print(f'Primo tick: {first_tick}')
    print(f'Ultimo tick: {last_tick}')
    
    # Range temporale
    first_ts = first_tick.ts_event / 1_000_000_000
    last_ts = last_tick.ts_event / 1_000_000_000
    first_date = datetime.fromtimestamp(first_ts)
    last_date = datetime.fromtimestamp(last_ts)
    
    print(f'\n=== COVERAGE TEMPORALE ===')
    print(f'📅 Inizio: {first_date.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'📅 Fine:   {last_date.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'📅 Durata: {(last_date - first_date).days} giorni')
    
    # Statistiche prezzi e volumi
    prices = [float(str(t.price)) for t in trade_ticks]
    volumes = [float(str(t.size)) for t in trade_ticks]
    
    print(f'\n=== STATISTICHE MERCATO ===')
    print(f'💰 Prezzo min:   ${min(prices):,.2f}')
    print(f'💰 Prezzo max:   ${max(prices):,.2f}')
    print(f'💰 Prezzo medio: ${sum(prices)/len(prices):,.2f}')
    print(f'📈 Volume totale: {sum(volumes):,.2f} BTC')
    print(f'📈 Volume medio:  {sum(volumes)/len(volumes):.6f} BTC per trade')
    
    # Validazione integrità
    print(f'\n=== VALIDAZIONE INTEGRITÀ ===')
    
    # Test ordinamento cronologico
    timestamps = [t.ts_event for t in trade_ticks]
    is_sorted = all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))
    print(f'✅ Ordinamento cronologico: {"CORRETTO" if is_sorted else "❌ ERRORE"}')
    
    # Test duplicati trade ID
    trade_ids = [t.trade_id.value for t in trade_ticks]
    unique_ids = set(trade_ids)
    duplicate_percentage = (len(trade_ids) - len(unique_ids)) / len(trade_ids) * 100
    print(f'🆔 Trade ID unici: {len(unique_ids):,} / {len(trade_ids):,}')
    print(f'🆔 Duplicati: {duplicate_percentage:.3f}%')
    
    # Test range ragionevoli
    price_ok = all(1000 <= p <= 100000 for p in prices[:1000])
    volume_ok = all(0.001 <= v <= 1000 for v in volumes[:1000])
    print(f'💰 Range prezzi ragionevoli: {"✅ OK" if price_ok else "❌ ANOMALIE"}')
    print(f'📊 Range volumi ragionevoli: {"✅ OK" if volume_ok else "❌ ANOMALIE"}')
    
    # Test distribuzione temporale
    months = {}
    for tick in trade_ticks[::10000]:
        ts = tick.ts_event / 1_000_000_000
        month = datetime.fromtimestamp(ts).strftime('%Y-%m')
        months[month] = months.get(month, 0) + 1
    
    print(f'\n=== DISTRIBUZIONE MENSILE (SAMPLE) ===')
    for month in sorted(months.keys()):
        print(f'📊 {month}: {months[month]:,} ticks (sample)')
    
    print(f'\n=== QUALITÀ DATASET ===')
    data_density = len(trade_ticks) / ((last_ts - first_ts) / 86400)
    print(f'📈 Densità dati: {data_density:,.0f} ticks/giorno')
    print(f'📈 Frequenza: {86400/data_density:.1f} secondi tra trade (media)')
    
    validation_ok = is_sorted and price_ok and volume_ok
    print(f'\n🎯 VALIDAZIONE: {"✅ DATASET VALIDO" if validation_ok else "❌ PROBLEMI RILEVATI"}')

else:
    print('❌ ERRORE: Nessun trade tick trovato nel catalog!')

print(f'\n📁 Catalog validato: {catalog_path}')
