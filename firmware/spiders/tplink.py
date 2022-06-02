from datetime import datetime
from typing import Generator, List, Optional

from scrapy import Request
from scrapy.http import Response

from firmware.custom_spiders import FirmwareSpider
from firmware.items import FirmwareItem


class TPLink(FirmwareSpider):
    handle_httpstatus_list = [404]
    name = 'tplink'

    allowed_domains = [
        'www.tp-link.com',
        'static.tp-link.com'
    ]

    start_urls = [
        'https://www.tp-link.com/de/home-networking/wifi-router/',  # these are routers without integrated modem
        'https://www.tp-link.com/de/home-networking/all-gateways/',  # these are routers with integrated modem
        'https://www.tp-link.com/de/home-networking/deco/',  # these are AIO access points like the fritz mesh solutions
        'https://www.tp-link.com/de/home-networking/mifi/',  # portable routers with 3G/4G modems
        'https://www.tp-link.com/de/home-networking/range-extender/',  # repeaters
        'https://www.tp-link.com/de/home-networking/powerline/',  # powerline adapters
        'https://www.tp-link.com/de/home-networking/access-point/',  # PoE-powered wifi access points
    ]

    custom_settings = {
        'ROBOTSTXT_OBEY': True,
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': True
    }

    xpath = {
        'products_on_page': '//a[contains(@class,"tp-product-link")]/@href',
        'product_pages': '//li[@class="tp-product-pagination-item"]/a[@class="tp-product-pagination-btn"]/@href',
        'product_name': '//h2[@class="product-name"]/text()|//label[@class="model-select"]/p/span/text()',
        'product_support_link': '//a[contains(@class,"support")]/@href',
        'firmware_download_link': '//tr[@class="basic-info"][1]//a[contains(@class, "download") and '
                                  '(contains(@data-vars-event-category, "Firmware") or '
                                  'contains(@href, "firmware"))]/@href',
        'device_revision': '//span[@id="verison-hidden"]/text()',
        'firmware_release_date': '//*[@id="content_Firmware"]/table//tr[@class="detail-info"][1]/td[1]/span[2]/text()[1]',   
    }

    def parse(self, response: Response, **kwargs: {}) -> Generator[Request, None, None]:
        for product_url in self.extract_products_on_page(response=response):
            yield Request(url=product_url, callback=self.parse_product_details)
        for page_url in self.extract_pages(response=response):
            yield Request(url=page_url, callback=self.parse)

    @classmethod
    def parse_product_details(cls, product_page: Response) -> List[Request]:
        device_name = product_page.xpath(cls.xpath['product_name']).extract()[0]
        device_class = cls.map_device_class(product_page.url)

        support_link = cls.extract_product_support_link(product_page)

        return [Request(
            url=support_link,
            callback=cls.parse_firmware,
            cb_kwargs=dict(device_name=device_name, device_class=device_class),
        )]

    @classmethod
    def parse_firmware(cls, support_page: Response, device_name: str, device_class: str) -> Generator[FirmwareItem, None, None]:
        file_url = cls.extract_firmware_download_link(support_page)
        if file_url is None:
            yield None
            return

        device_revision = cls.extract_device_revision(support_page)
        firmware_release_date = cls.extract_firmware_release_date(support_page)

        if any(var is None for var in [device_name, device_class, file_url, device_revision, firmware_release_date]):
            raise ValueError

        meta_data = cls.prepare_meta_data(device_name, device_class, file_url, device_revision,
                                          firmware_release_date)
        yield from cls.item_pipeline(meta_data)

    @staticmethod
    def prepare_meta_data(device_name: str, device_class: str, file_url: str, device_revision: str,
                          firmware_release_date) -> dict:
        return {
            'file_urls': [file_url],
            'vendor': 'TP-Link',
            'device_name': f'{device_name} {device_revision}',
            'firmware_version': file_url.replace('.zip', '').split('_')[-1],
            'device_class': device_class,
            'release_date': datetime.strptime(firmware_release_date.strip(), '%Y-%m-%d').strftime('%d-%m-%Y')
        }

    @classmethod
    def extract_products_on_page(cls, response: Response) -> Generator[str, None, None]:
        for result in response.xpath(cls.xpath['products_on_page']).extract():
            yield response.urljoin(result)

    @classmethod
    def extract_product_support_link(cls, product_page: Response) -> str:
        return product_page.urljoin(product_page.xpath(cls.xpath['product_support_link']).extract()[0])

    @classmethod
    def extract_firmware_download_link(cls, support_page: Response) -> Optional[str]:
        link_matches = support_page.xpath(cls.xpath['firmware_download_link']).extract()
        if len(link_matches) < 1:
            return None
        return support_page.urljoin(link_matches[0])

    @classmethod
    def extract_device_revision(cls, support_page: Response) -> str:
        return support_page.xpath(cls.xpath['device_revision']).extract()[0]

    @classmethod
    def extract_firmware_release_date(cls, support_page: Response) -> str:
        return support_page.xpath(cls.xpath['firmware_release_date']).extract()[0]

    @classmethod
    def extract_pages(cls, response: Response) -> Generator[str, None, None]:
        for page in response.xpath(cls.xpath['product_pages']).extract():
            yield response.urljoin(page)

    @staticmethod
    def map_device_class(product_url: str) -> str:
        if any(kw in product_url for kw in ['wifi-router', 'all-gateways', 'mifi']):
            return 'Router'
        if 'range-extender' in product_url:
            return 'Repeater'
        if 'powerline' in product_url:
            return 'PLC Adapter'
        if any(kw in product_url for kw in ['access_point', 'deco']):
            return 'AP'
        return 'Router'
#
