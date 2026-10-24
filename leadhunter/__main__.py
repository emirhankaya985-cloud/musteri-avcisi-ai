"""Run demo or live opportunity scan."""
import argparse
from pathlib import Path
from .core import live, format_telegram

def main():
    parser = argparse.ArgumentParser(description='Müşteri Avcısı AI')
    parser.add_argument('mode', choices=('demo', 'live'))
    args = parser.parse_args()
    if args.mode == 'live':
        live()
        return
    samples = [
        {'id':'node/1', 'name':'ÖRNEK Atlas Oto Yıkama', 'category':'Oto yıkama',
         'website':'', 'phone':'(örnek)', 'address':'Kadıköy (örnek)', 'score':100},
        {'id':'node/2', 'name':'ÖRNEK Mira Kuaför', 'category':'Kuaför/berber',
         'website':'https://example.com', 'phone':'', 'address':'', 'score':45}
    ]
    path = Path('dist/telegram-demo.txt')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n\n---\n\n'.join(format_telegram(x, demo=True) for x in samples),
                    encoding='utf-8')
    print('Oluşturuldu: dist/telegram-demo.txt — sentetik veri; mesaj gönderilmedi.')

if __name__ == '__main__':
    main()
