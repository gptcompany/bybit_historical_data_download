#!/usr/bin/env python3
import json
import zipfile
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog
import time

print('=== IMPORT ORDERBOOK 2024 ===')

orderbook_dir = Path('/media/sam/2TB-NVMe/bybit_data_downloader/nautilus_data/orderbook_deltas/contract/orderbook/BTCUSDT')
catalog_path = '/media/sam/2TB-NVMe/bybit_data_downloader/bybit_nautilus_2020_full'

zip_files = list(orderbook_dir.glob('*.zip'))
print(f'ZIP files found: {len(zip_files)}')

for zip_file in zip_files:
    print(f'\nProcessing: {zip_file.name}')
    
    with zipfile.ZipFile(zip_file, 'r') as zf:
        data_file = zf.namelist()[0]
        print(f'Data file: {data_file}')
        
        start_time = time.time()
        message_count = 0
        
        with zf.open(data_file) as file:
            for line in file:
                if line.strip():
                    try:
                        msg = json.loads(line.decode('utf-8'))
                        message_count += 1
                        
                        if message_count % 100000 == 0:
                            elapsed = time.time() - start_time
                            print(f'  Processed {message_count:,} messages in {elapsed:.1f}s')
                            
                        if message_count >= 1000000:  # Limit per testing
                            break
                            
                    except:
                        continue
        
        total_time = time.time() - start_time
        print(f'  Total: {message_count:,} messages in {total_time:.1f}s')
        print(f'  Rate: {message_count/total_time:.0f} msg/sec')

print(f'\n✅ ORDERBOOK ANALYSIS COMPLETE')
print(f'Note: Orderbook deltas require specialized handling')
print(f'Structure: JSON line-delimited with snapshot + delta messages')
print(f'Ready for: Custom orderbook delta processor')
