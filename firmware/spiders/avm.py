import os
import re
from json import loads
from typing import Generator, Union

from scrapy import Request
from scrapy.http import Response

from firmware.custom_requests import FTPFileRequest, FTPListRequest
from firmware.custom_spiders import FTPSpider
from firmware.items import FirmwareItem


class AVM(FTPSpider):
    handle_httpstatus_list = [404]
    name = 'avm'
    allowed_domains = ['ftp.avm.de', 'avm.de']
    start_urls = ['ftp://ftp.avm.de/']

    custom_settings = {
        # robots.txt is not an FTP concept
        'ROBOTSTXT_OBEY': False,
        # being nice to AVM servers
        'CONCURRENT_REQUESTS': 1,
        'CONCURRENT_ITEMS': 1,
        'DOWNLOAD_DELAY': 0.75,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'REFERER_ENABLED': False
    }

    filter_eol_products = True

    meta_regex = {
        'device_name': re.compile(r'^Produkt\s*:\s+(.*)$', flags=re.MULTILINE | re.IGNORECASE),
        'firmware_version': re.compile(r'^Version\s*:\s+(.*)$', flags=re.MULTILINE | re.IGNORECASE),
        'release_date': re.compile(r'^Release-Datum\s*:\s+(.*)$', flags=re.MULTILINE | re.IGNORECASE)
    }

    def parse(self, response: Response, **kwargs):  # pylint: disable=unused-argument
        folder = loads(response.body)

        yield from self.recurse_sub_folders(folder, base_url=response.url)
        yield from self.search_firmware_images(folder, base_url=response.url)

    def parse_metadata_and_download_image(self, response: Response, image_path, **kwargs) -> Generator[Union[Request, FirmwareItem], None, None]:  # pylint: disable=unused-argument
        info_de_txt = response.body.decode('latin-1')

        meta_data = {
            'vendor': 'AVM',
            'file_urls': [image_path],
            'device_name': self.meta_regex['device_name'].findall(info_de_txt)[0].strip(),
            'device_class': self.map_device_class(image_path=image_path),
            'firmware_version': self.meta_regex['firmware_version'].findall(info_de_txt)[0].strip().split(' ')[-1],
            'release_date': self.meta_regex['release_date'].findall(info_de_txt)[0].strip().replace('.', '-').replace('/', '-')
        }

        if self.filter_eol_products:
            product_path = image_path.split('/')[-4]
            product_line = image_path.split('/')[-5]
            yield Request(f'https://avm.de/produkte/{product_line}/{product_path}', callback=self.verify_support, cb_kwargs={'meta_data': meta_data})
        else:
            yield from self.item_pipeline(meta_data)

    def search_firmware_images(self, folder: list, base_url: str) -> Generator[FTPFileRequest, None, None]:
        for image in self._image_file_filter(folder):
            image_path = os.path.join(base_url, image['filename'])
            info_path = os.path.join(base_url, 'info_de.txt')
            yield FTPFileRequest(info_path, callback=self.parse_metadata_and_download_image, cb_kwargs={'image_path': image_path})

    def verify_support(self, response: Response, meta_data: dict, **kwargs):  # pylint: disable=unused-argument
        if response.status == 200:
            yield from self.item_pipeline(meta_data)

    @staticmethod
    def _folder_filter(entries):
        for entry in entries:
            if any([entry['filetype'] != 'd',
                    entry['filename'] in ['..', 'archive', 'beta', 'other', 'recover', 'belgium', 'tools', 'switzerland'],
                    entry['linktarget'] is not None]):
                continue
            yield entry

    @staticmethod
    def _image_file_filter(entries: list):
        for entry in entries:
            if any([entry['filetype'] != '-',
                    not entry['filename'].endswith(('.image', '.zip')),
                    entry['linktarget'] is not None]):
                continue
            yield entry

    @classmethod
    def recurse_sub_folders(cls, folder: list, base_url: str):
        for sub_folder in cls._folder_filter(folder):
            name = sub_folder['filename']
            recursive_path = f'{os.path.join(base_url, name)}/'
            yield FTPListRequest(recursive_path)

    @staticmethod
    def map_device_class(image_path: str) -> str:
        # /fritzbox/<PRODUCT_PARENT>/<locale>/fritz.os/<image>
        product_parent = image_path.split('/')[-4]
        if product_parent.startswith(('fritzrepeater', 'fritzwlan-repeater')):
            return 'Repeater'
        if product_parent.startswith('fritzwlan-usb'):
            return 'Wifi-Stick'
        if product_parent.startswith('fritzpowerline'):
            return 'PLC Adapter'
        return 'Router'
