from datetime import datetime
from typing import Generator

from scrapy import Request
from scrapy.http import Response

from firmware.custom_spiders import FirmwareSpider
from firmware.items import FirmwareItem


class Zyxel(FirmwareSpider):
    name = 'zyxel'
    manufacturer = 'ZYXEL'

    start_urls = [
        'https://www.zyxel.com/products_services/home_connectivity-wifi_router.shtml?t=c',  # router
        'https://www.zyxel.com/products_services/home_connectivity-wifi_system.shtml?t=c',  # mesh
        'https://www.zyxel.com/products_services/home_connectivity-wifi_extender.shtml?t=c',  # extender
    ]

    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        # being nice to ZYXEL servers
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': False,
    }

    xpath = {
        'get_product_urls': '//div[@class="card"]/a/@href',
        'get_device_name': '//p[@class="text-series"]/text()',
        'get_firmware_page_url': '//a[contains(@href, "&tab=Firmware")]/@href',
        'get_download_link': '//a[contains(@data-filelink, "/firmware/") and contains(@data-filelink, ".zip")]/@data-filelink',
        'get_firmware_version': '//a[contains(@data-filelink, "/firmware/") and contains(@data-filelink, ".zip")]/@data-version',
        'get_release_date': '//td[contains(@class, "dateTd")]/span/text()',
    }

    def parse(self, response: Response, **kwargs) -> Generator[Request, None, None]:
        product_urls = response.xpath(self.xpath['get_product_urls']).extract()
        device_names = response.xpath(self.xpath['get_device_name']).extract()

        for product_url, device_name in zip(product_urls, device_names):
            product_download_pages_url = f'{product_url}downloads'
            yield Request(
                url=response.urljoin(product_download_pages_url),
                callback=self.move_to_firmware_downloads,
                cb_kwargs=dict(device_name=device_name)
            )

    def move_to_firmware_downloads(self, response: Response, device_name: str) -> Generator[Request, None, None]:
        firmware_page_url = response.xpath(self.xpath['get_firmware_page_url']).get()
        yield Request(
            url=response.urljoin(firmware_page_url),
            callback=self.parse_firmware_table,
            cb_kwargs=dict(device_name=device_name),
        )

    def parse_firmware_table(self, response: Response, device_name: str) -> Generator[FirmwareItem, None, None]:
        download_link = response.xpath(self.xpath['get_download_link']).get()
        firmware_version = response.xpath(self.xpath['get_firmware_version']).get()
        dirty_release_date = response.xpath(self.xpath['get_release_date']).get()

        if None in [download_link, firmware_version, dirty_release_date]:
            yield from []
            return

        release_date = datetime.strptime(dirty_release_date.strip(), '%b %d, %Y').strftime('%d-%m-%Y')

        meta_data = {
            'vendor': 'zyxel',
            'release_date': release_date,
            'device_name': device_name,
            'firmware_version': firmware_version,
            'device_class': self.map_device_class(device_name),
            'file_urls': [download_link],
        }

        yield from self.item_pipeline(meta_data=meta_data)

    @staticmethod
    def map_device_class(device_name: str) -> str:
        if device_name.startswith(('Armor', 'NBG')):
            return 'Router (Home)'
        if device_name.startswith('Multy'):
            return 'Mesh'
        if device_name.startswith(('WAP', 'NWD', 'WRE')):
            return 'Extender'
        return 'unknown'
