import json
import re
from contextlib import suppress
from datetime import datetime
from json import JSONDecodeError
from typing import Generator, List, Optional

from scrapy import Request
from scrapy.http import Response

from firmware.custom_spiders import FirmwareSpider
from firmware.items import FirmwareItem


class Asus(FirmwareSpider):
    name = 'asus'
    manufacturer = 'ASUS'

    start_urls = ['https://odinapi.asus.com/recent-data/apiv2/SeriesFilterResult?SystemCode=asus&WebsiteCode=de&ProductLevel1Code=Networking-IoT-Servers&ProductLevel2Code=Wifi-Routers&PageSize=100&PageIndex=1&CategoryName=&SeriesName=ROG-Republic-of-Gamers,ASUS-Gaming-Routers,ASUS-WiFi-Routers&SubSeriesName=&Spec=&SubSpec=&Sort=Recommend&siteID=www&sitelang=']  # pylint: disable=line-too-long

    custom_settings = {
        'ROBOTSTXT_OBEY': True,
        # being nice to AVM servers
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': False
    }

    def parse(self, response: Response, **kwargs) -> Generator[Request, None, None]:
        try:
            data = json.loads(response.body.decode())
        except (UnicodeDecodeError, JSONDecodeError):
            yield None
            return

        for product in data['Result']['ProductList']:
            product_url = product['ProductURL']
            product_id = product['RealProductID']
            hash_id = product['ProductHashedID']
            # Some device names contain html tags for formatting, strip them
            device_name = re.sub('<[^<]+?>', '', product['Name']).strip()
            model_reference = product_url.split('/')[-2]
            yield Request(
                url=self.construct_url_based_on_reference(model_reference, hash_id, product_id),
                callback=self.parse_pdbios,
                cb_kwargs=dict(device_name=device_name)
            )

    @staticmethod
    def construct_url_based_on_reference(model_reference: str, hash_id: str, product_id: str) -> str:
        if model_reference.startswith('rog-'):
            return f'https://rog.asus.com/support/webapi/product/GetPDBIOS?website=de&model={model_reference}&cpu=&pdid={product_id}'
        return f'https://www.asus.com/support/api/product.asmx/GetPDBIOS?website=de&model={model_reference}&pdhashedid={hash_id}'

    def parse_pdbios(self, response: Response, device_name: str) -> Generator[FirmwareItem, None, None]:
        try:
            data = json.loads(response.body.decode())
        except (UnicodeDecodeError, JSONDecodeError):
            yield None
            return

        firmwares = self.extract_firmware_files(data)
        latest_firmware = self.get_latest_firmware(firmwares)

        if latest_firmware is None:
            yield None
            return

        meta_data = {
            'vendor': 'asus',
            'release_date': datetime.strptime(latest_firmware['ReleaseDate'], '%Y/%m/%d').strftime('%d-%m-%Y'),
            'device_name': device_name,
            'firmware_version': latest_firmware['Version'],
            'device_class': 'Router (Home)',
            'file_urls': latest_firmware['DownloadUrl']['Global']
        }
        yield from self.item_pipeline(meta_data)

    @staticmethod
    def get_latest_firmware(firmwares: List[dict]) -> Optional[dict]:
        with suppress(KeyError):
            for firmware in firmwares:
                if firmware['IsRelease'] == '1':
                    return firmware
        return None

    @staticmethod
    def extract_firmware_files(data: dict) -> List[dict]:
        with suppress(KeyError):
            for obj in data['Result']['Obj']:
                if obj['Name'] == 'Firmware':
                    return obj['Files']
        return []
