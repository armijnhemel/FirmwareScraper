import logging
import re
from typing import Generator

from scrapy import Request
from scrapy.http import Response

from firmware.custom_spiders import FirmwareSpider
from firmware.items import FirmwareItem


class Netgear(FirmwareSpider):
    name = 'netgear'
    manufacturer = 'NETGEAR'

    start_urls = [
        'https://www.netgear.com/de/home/wifi/routers/',  # router
        'https://www.netgear.com/de/home/wifi/range-extenders/',  # repeater
        'https://www.netgear.com/de/home/wifi/mesh/',  # mesh
        'https://www.netgear.com/de/home/online-gaming/routers/',  # 'gaming' router
        'https://www.netgear.com/de/home/mobile-wifi/hotspots/'  # 4g/5g router
        'https://www.netgear.com/de/home/mobile-wifi/lte-modems/',  # 4g/5g router
    ]

    custom_settings = {
        # Sorry.
        'ROBOTSTXT_OBEY': False,
        # being nice to Netgear servers
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': False
    }

    xpath = {
        'get_product_text': '//p[@class="eyebrow-small"]/a/text()',
        'get_kb_article': '//a/p[contains(text(), "Firmware")]/parent::a/following-sibling::a[contains(@href, "kb.netgear.com")]/@href',
        'get_download_link': '//a/p[contains(text(), "Firmware")]/parent::a/@href',
        'get_version': '//a/p[contains(text(), "Firmware")]/text()',
        'get_release_date': '//p[@class="last-updated"]/text()',
    }

    regex = {
        'get_device_name': re.compile(r'\((\w+)\)$', flags=re.MULTILINE)
    }

    def parse(self, response: Response, **kwargs) -> Generator[Request, None, None]:
        product_texts = response.xpath(self.xpath['get_product_text']).extract()

        for text in product_texts:
            device_name = self.regex['get_device_name'].findall(text)[0]
            yield Request(
                url=f'https://www.netgear.de/support/download/default.aspx?model={device_name}',
                callback=self.consult_support_pages,
                cb_kwargs=dict(device_name=device_name),
                meta=dict(selenium=True)  # required because the xpath queries need a properly built DOM tree via JS
            )

    def consult_support_pages(self, response: Response, device_name: str) -> Generator[Request, None, None]:
        kb_article_link = response.xpath(self.xpath['get_kb_article']).get()
        download_link = response.xpath(self.xpath['get_download_link']).get()
        dirty_version = response.xpath(self.xpath['get_version']).get()

        if None in [kb_article_link, download_link, dirty_version]:
            logging.warning([kb_article_link, download_link, dirty_version])
            yield from []
            return
        firmware_version = dirty_version.split(' ')[-1].strip()

        yield Request(
            url=kb_article_link,
            callback=self.parse_kb_article,
            cb_kwargs=dict(firmware_version=firmware_version, download_link=download_link, device_name=device_name)
        )

    def parse_kb_article(self, response: Response, device_name: str, firmware_version: str, download_link: str) -> Generator[FirmwareItem, None, None]:

        dirty_release_date = response.xpath(self.xpath['get_release_date']).get()

        release_date = dirty_release_date.split(':')[-1].strip().replace('/', '-')

        meta_data = {
            'vendor': 'netgear',
            'release_date': release_date,
            'device_name': device_name,
            'firmware_version': firmware_version,
            'device_class': self.map_device_class(device_name),
            'file_urls': [download_link.strip()]
        }
        yield from self.item_pipeline(meta_data)

    @staticmethod
    def map_device_class(device_name: str) -> str:
        if device_name.startswith(('RBK', 'RBS', 'MK', 'MS')):
            return 'Mesh'
        if device_name.startswith(('EAX', 'EX')):
            return 'Repeater'
        if device_name.startswith(('MR', 'AC', 'LM', 'LB', 'NBK', 'LAX')):
            return 'Router (Mobile)'
        if device_name.startswith(('RAX', 'XR', 'RS', 'R')):
            return 'Router (Home)'
        return 'unknown'
