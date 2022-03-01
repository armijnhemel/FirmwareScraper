import re
from typing import Generator, Optional, Tuple

from scrapy import Request
from scrapy.http import Response

from firmware.custom_spiders import FirmwareSpider
from firmware.items import FirmwareItem


class ClassIdentifier:
    def __init__(self, shortcuts: tuple):
        self.shortcuts: tuple = shortcuts


class Linksys(FirmwareSpider):
    PRODUCT_DICTIONARIES = []
    handle_httpstatus_list = [404]
    name = 'linksys'

    device_classes = {
        ClassIdentifier(('AM', )): 'Modem',
        ClassIdentifier(('CIT', )): 'Internet Telephone',
        ClassIdentifier(('EF', 'EP', 'PPS', 'PSU', 'WPS')): 'Print Server',
        ClassIdentifier(('DMP', 'DMC', 'DMR', 'DMS', 'KWH', 'MCC')): 'Wireless Home Audio',
        ClassIdentifier(('DMA', )): 'Media Center Extender',
        ClassIdentifier(('LACP', )): 'Injector',
        ClassIdentifier(('LACX', 'LACG')): 'Transceiver',
        ClassIdentifier(('LAPN', 'LAPAC')): 'Business Access Point',
        ClassIdentifier(('LCA', )): 'Business Camera',
        ClassIdentifier(('LMR', 'LNR')): 'Business Video Recorder',
        ClassIdentifier(('LNE', 'EG', 'WMP')): 'PCI Network Adapter',
        ClassIdentifier(('LRT', )): 'VPN Router',
        ClassIdentifier(('LGS', )): 'Business Switch',
        ClassIdentifier(('MR', 'EA', 'WRT', 'E', 'BEF', 'WKU', 'WRK')): 'Router',
        ClassIdentifier(('M10', 'M20')): 'Hotspot',
        ClassIdentifier(('NMH', )): 'Media Hub',
        ClassIdentifier(('NSL', )): 'Network Storage Link',
        ClassIdentifier(('PCM', )): 'CardBus PC Card',
        ClassIdentifier(('PL', )): 'PLC Adapter',
        ClassIdentifier(('RE', 'WRE')): 'Repeater',
        ClassIdentifier(('SE', 'EZX')): 'Home Switch',
        ClassIdentifier(('WAP', )): 'Home Access Point',
        ClassIdentifier(('WET', 'WUM', 'WES')): 'Bridge',
        ClassIdentifier(('WGA', 'WMA', 'WPC')): 'Wireless Adapter',
        ClassIdentifier(('WHW', 'VLP', 'MX')): 'Wifi Mesh System',
        ClassIdentifier(('WMC', 'WVC')): 'Home Camera',
        ClassIdentifier(('WML', )): 'Music System',
        ClassIdentifier(('WUSB', 'USB', 'AE')): 'Wifi USB Adapter',
        ClassIdentifier(('X', 'AG', 'WAG')): 'Modem Router'
    }

    custom_settings = {
        # robots.txt is not an FTP concept
        'ROBOTSTXT_OBEY': False,
        # being nice to AVM servers
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': True
    }

    xpath = {
        'product_urls_on_page': '//a[@class="thumb"]/@href',
        'get_download_page': '//*[contains(text(), "Firmware-Verbesserungen")]/following::p[1]/'
                             'a[contains(text(), "herunterladen")]/@href',
        'download_link': '//*[contains(text(), "Firmware")]//ancestor::*//a[contains(@href, "firmware")]/@href',
        'date_and_version': '//*[contains(text(), "Firmware")]//ancestor::*//*[contains(text(), "Ver. ") or contains(text(), "Version: ")]/text()',
        'product_name': '//*[@class="part-number"]/text()',
    }

    start_urls = [
        'https://www.linksys.com/de/c/whole-home-mesh-wifi/?q=%3AsortByProductRank&page=0',
        'https://www.linksys.com/de/c/WLAN-Router/?q=%3AsortByProductRank&page=0',
        'https://www.linksys.com/de/c/wlan-range-extender/?q=%3AsortByProductRank&page=0',
        'https://www.linksys.com/de/c/Netzwerk-Switches/?q=%3AsortByProductRank&page=0',
    ]

    regex = {
        'get_support_page': re.compile(r'var _supportProductID = "([\dA-Za-z]+)";', flags=re.MULTILINE)
    }

    allowed_domains = ['www.linksys.com', 'downloads.linksys.com']

    def start_requests(self):
        for url in self.start_urls:
            yield Request(url, cb_kwargs=dict(page=0))

    def parse(self, response: Response, **kwargs) -> Generator[Request, None, None]:  # pylint disable=unused-argument
        # reached last page in the previous request
        if '0 Produkte gefunden' in response.body.decode():
            return

        page = kwargs['page']

        for product_url in response.xpath(self.xpath['product_urls_on_page']).extract():
            yield Request(url=response.urljoin(product_url), callback=self.move_to_support_page)

        # move to next page in product catalogue
        next_page = page + 1
        yield Request(url=f'{response.url.rpartition("=")[0]}={next_page}', cb_kwargs=dict(page=next_page))

    def move_to_support_page(self, response: Response) -> Optional[Request]:
        support_page_matches = self.regex['get_support_page'].findall(response.body.decode())
        if len(support_page_matches) < 1:
            return None
        return Request(url=response.urljoin(f'/de/support-product?rnId={support_page_matches[0]}'),
                       callback=self.move_to_download_page)

    @classmethod
    def extract_date_and_version(cls, response: Response) -> Tuple[str, str]:
        matches = response.xpath(cls.xpath['date_and_version']).extract()
        if len(matches) < 2:
            return '', ''

        firmware_version = matches[0].replace('Ver.', '')
        release_date = matches[1].split(' ')[-1].replace('/', '-')
        return firmware_version, release_date

    def move_to_download_page(self, response: Response) -> Optional[Request]:
        download_page_matches = response.xpath(self.xpath['get_download_page']).extract()
        if len(download_page_matches) < 1:
            return None

        product_name_matches = response.xpath(self.xpath['product_name']).extract()
        if len(product_name_matches) < 1:
            return None

        device_name = product_name_matches[0][4:]
        return Request(url=response.urljoin(download_page_matches[0]), callback=self.parse_download_page,
                       cb_kwargs=dict(device_name=device_name), dont_filter=True)

    def parse_download_page(self, response: Response, device_name: str) -> Generator[FirmwareItem, None, None]:
        download_matches = response.xpath(self.xpath['download_link']).extract()
        if len(download_matches) < 1:
            return

        file_url = download_matches[0]
        firmware_version, release_date = self.extract_date_and_version(response)
        device_class = self.map_device_class(device_name)

        meta_data = {
            'vendor': 'Linksys',
            'file_urls': [file_url],
            'device_name': device_name,
            'device_class': device_class,
            'firmware_version': firmware_version.strip(),
            'release_date': release_date,
        }

        yield from self.item_pipeline(meta_data)

    @classmethod
    def map_device_class(cls, device_name: str) -> str:
        for identifiers, device_class in cls.device_classes.items():
            if device_name.startswith(identifiers.shortcuts):
                return device_class
        return ''
