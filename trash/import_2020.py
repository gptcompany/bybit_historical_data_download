#!/usr/bin/env python3
import pandas as pd
import gzip
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.enums import AggressorSide
import time
import glob

print('=== IMPORT 17 FILES CONTRACT 2020 ===')

catalog_path = '/media/sam/2TB-NVMe/bybit_data_downloader/bybit_nautilus_2020_full'
catalog = ParquetDataCatalog(catalog_path)
instrument_id = InstrumentId.from_str('BTCUSDT-LINEAR.BYBIT')

search_paths = [
    '/media/sam/2TB-NVMe/bybit_data_downloader/nautilus_data/trade_ticks/contract/trade/BTCUSDT/',
    '/media/sam/2TB-NVMe/bybit_data_downloader/downloaded_data/contract/trade/BTCUSDT/'
]

contract_files = []
for search_path in search_paths:
    if Path(search_path).exists():
        files = glob.glob(f'{search_path}/*2020*.csv.gz')
        contract_files.extend(files)

contract_files = sorted(list(set(contract_files)))
print(f'Files trovati: {len(contract_files)}')

start_time = time.time()
all_ticks = []

for i, csv_file in enumerate(contract_files, 1):
    print(f'[{i}/{len(contract_files)}] {Path(csv_file).name}...')
    
    with gzip.open(csv_file, 'rt') as f:
        df = pd.read_csv(f)
    
    for _, row in df.iterrows():
        ts_event = int(row['timestamp'] * 1_000_000_000)
        aggressor_side = AggressorSide.BUYER if row['side'] == 'Buy' else AggressorSide.SELLER
        
        tick = TradeTick(
            instrument_id=instrument_id,
            price=Price.from_str(str(row['price'])),
            size=Quantity.from_str(str(row['size'])),
            aggressor_side=aggressor_side,
            trade_id=TradeId(str(row['trdMatchID'])),
            ts_event=ts_event,
            ts_init=ts_event
        )
        all_ticks.append(tick)

print(f'\nProcessed {len(all_ticks):,} ticks from {len(contract_files)} files')
print('Sorting and writing to catalog...')

all_ticks.sort(key=lambda x: x.ts_event)
catalog.write_data(all_ticks)

end_time = time.time()

total_ticks = catalog.trade_ticks([instrument_id])
print(f'\n=== RISULTATI ===')
print(f'Import time: {end_time - start_time:.1f}s')
print(f'Total ticks: {len(total_ticks):,}')

if total_ticks:
    from datetime import datetime
    first_ts = total_ticks[0].ts_event / 1_000_000_000
    last_ts = total_ticks[-1].ts_event / 1_000_000_000
    first_date = datetime.fromtimestamp(first_ts).strftime('%Y-%m-%d')
    last_date = datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d')
    
    prices = [float(str(t.price)) for t in total_ticks]
    volumes = [float(str(t.size)) for t in total_ticks]
    
    print(f'Date range: {first_date} to {last_date}')
    print(f'Price range: ${min(prices):,.0f} - ${max(prices):,.0f}')
    print(f'Total volume: {sum(volumes):,.1f} BTC')
    print(f'\n✅ CONTRACT 2020 DATASET READY')

print(f'\n📊 Catalog: {catalog_path}')
