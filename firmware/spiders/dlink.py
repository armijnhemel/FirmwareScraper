from datetime import datetime
from typing import Generator

from scrapy import Request, Spider
from scrapy.http import Response
from scrapy.loader import ItemLoader

from firmware.items import FirmwareItem


class DLink(Spider):
    handle_httpstatus_list = [404]
    name = 'dlink'
    allowed_domains = ['eu.dlink.com', 'ftp.dlink.de']

    start_urls = [
        'https://eu.dlink.com/de/de/for-home/wifi?mode=ajax&filters=&categories=&page=-1&target=products',  # wifi/routers, 4g/5g
        'https://eu.dlink.com/de/de/for-home/cameras?mode=ajax&filters=&categories=&page=-1&target=products',  # ip cams
        'https://eu.dlink.com/de/de/for-home/smart-home?mode=ajax&filters=&categories=&page=-1&target=products',  # smart home
        'https://eu.dlink.com/de/de/for-home/switches?mode=ajax&filters=&categories=&page=-1&target=products',  # switches
    ]

    custom_settings = {
        # We're bad here, I know. But we drastically reduce traffic for both sides by using the endpoints above
        'ROBOTSTXT_OBEY': False,
        # Still trying to be nice to DLink servers
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': True,
    }

    xpath = {
        'product_names_in_category': '//div[@class="product-item__number"]/text()',
        'detail_pages_in_category': '//div[@class="product-item__number"]/parent::a/@href',
        'detail_latest_revision_name': '//select[@id="supportRevision"]/option[last()]/text()',
        'detail_latest_revision_param': '//select[@id="supportRevision"]/option[last()]/@value',
        'version': '//div[@id="firmware"]//td[@data-table-header="Version"]/text()',
        'date': '//div[@id="firmware"]//td[@data-table-header="Datum"]/text()',
        'download_link': '//div[@id="firmware"]//td[@data-table-header=""]/a/@href',
    }

    device_classes_dict = {
        'dba': 'Access Point', 'dap': 'Access Point',
        'dis': 'Converter', 'dmc': 'Converter',
        'dge': 'PCIe-Networkcard', 'dwa': 'PCIe-Networkcard', 'dxe': 'PCIe-Networkcard',
        'dps': 'Redundant Power Supply',
        'dsr': 'Router (Business)',
        'dwr': 'Router (mobile)', 'dwm': 'Router (mobile)',
        'dsl': 'Router (Modem)',
        'covr': 'Router (Home)', 'dir': 'Router (Home)', 'dva': 'Router (Home)', 'go': 'Router (Home)',
        'dsp': 'Smart Plug',
        'dcs': 'Smart Wi-Fi Camera', 'dsh': 'Smart Wi-Fi Camera',
        'des': 'Switch', 'dgs': 'Switch', 'dkvm': 'Switch', 'dqs': 'Switch', 'dxs': 'Switch',
        'dem': 'Transceiver',
        'dub': 'USB Extensions',
        'dnr': 'Video Recorder',
        'dwc': 'Wireless Controller',
        'dwl': 'other'
    }

    def parse(self, response: Response, **kwargs) -> Generator[Request, None, None]:  # pylint: disable=unused-argument
        names = response.xpath(DLink.xpath['product_names_in_category']).extract()
        detail_links = response.xpath(DLink.xpath['detail_pages_in_category']).extract()
        for name, detail_link in zip(names, detail_links):
            yield Request(url=response.urljoin(detail_link), callback=self.process_detail_page, cb_kwargs=dict(product_name=name))

    def process_detail_page(self, response: Response, product_name: str, product_revision: str = ''):
        if product_revision == '':
            latest_revision_on_page = response.xpath(DLink.xpath['detail_latest_revision_name']).extract()
            latest_revision_query_param = response.xpath(DLink.xpath['detail_latest_revision_param']).extract()

            if len(latest_revision_on_page + latest_revision_query_param) > 0:
                yield Request(
                    url=response.urljoin(f'?revision={latest_revision_query_param[0]}'),
                    callback=self.process_detail_page,
                    cb_kwargs=dict(product_name=product_name, product_revision=latest_revision_on_page[0])
                )
                return

        version = response.xpath(DLink.xpath['version']).extract()
        release_date = response.xpath(DLink.xpath['date']).extract()
        download_link = response.xpath(DLink.xpath['download_link']).extract()

        if len(download_link + release_date + version) != 3:
            return

        meta_data = {
            'vendor': 'DLink',
            'file_urls': [download_link[0]],
            'device_name': f'{product_name} {product_revision}'.strip(),
            'device_class': self.map_device_class(download_link[0]),
            'firmware_version': version[0],
            'release_date': datetime.strptime(release_date[0].strip(), '%d.%m.%Y').strftime('%d-%m-%Y')
        }

        yield from self.item_pipeline(meta_data)

    @staticmethod
    def item_pipeline(meta_data: dict) -> Generator[FirmwareItem, None, None]:
        loader = ItemLoader(item=FirmwareItem(), selector=meta_data['file_urls'])
        for key, value in meta_data.items():
            loader.add_value(key, value)
        yield loader.load_item()

    @staticmethod
    def map_device_class(image_path: str) -> str:
        device_class = 'unknown'
        for key, value in DLink.device_classes_dict.items():
            if key in image_path.lower():
                device_class = value
                break
        return device_class
