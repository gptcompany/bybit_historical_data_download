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

print('=== IMPORT FULL 2020 CONTRACT DATA (245 FILES) ===')

catalog_path = '/media/sam/2TB-NVMe/bybit_data_downloader/bybit_nautilus_2020_COMPLETE'
catalog = ParquetDataCatalog(catalog_path)
instrument_id = InstrumentId.from_str('BTCUSDT-LINEAR.BYBIT')

# Main historical directory with 245 files
historical_dir = '/media/sam/2TB-NVMe/bybit_data_downloader/data/historical/trade/contract/BTCUSDT/contract/trade/BTCUSDT/'
contract_files = glob.glob(f'{historical_dir}*2020*.csv.gz')
contract_files = sorted(contract_files)

print(f'Files found: {len(contract_files)}')
print(f'First: {Path(contract_files[0]).name}')
print(f'Last: {Path(contract_files[-1]).name}')

start_time = time.time()
all_ticks = []
processed_count = 0

for i, csv_file in enumerate(contract_files, 1):
    if i % 50 == 0:
        print(f'[{i}/{len(contract_files)}] Progress: {len(all_ticks):,} ticks...')
    
    try:
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
        
        processed_count += 1
        
    except Exception as e:
        print(f'Error {Path(csv_file).name}: {e}')

print(f'\nProcessed {processed_count}/{len(contract_files)} files')
print(f'Total ticks: {len(all_ticks):,}')
print('Sorting by timestamp...')

all_ticks.sort(key=lambda x: x.ts_event)

print('Writing to catalog...')
catalog.write_data(all_ticks)

end_time = time.time()

total_ticks = catalog.trade_ticks([instrument_id])
print(f'\n=== FULL 2020 RESULTS ===')
print(f'Import time: {(end_time - start_time)/60:.1f} minutes')
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
    print(f'Total volume: {sum(volumes):,.0f} BTC')
    print(f'\n🎯 COMPLETE 2020 CONTRACT DATASET READY')

print(f'\n📊 Catalog: {catalog_path}')
