#!/usr/bin/env python
# vim:fileencoding=utf-8

__license__ = 'MIT'
__copyright__ = '2024, Artur Kupiec'

import os
from calibre.gui2 import error_dialog
from calibre.gui2 import warning_dialog
from calibre.gui2.tweak_book import current_container
from calibre.gui2.tweak_book.plugin import Tool

from calibre.ebooks.oeb.base import JPEG_MIME, PNG_MIME, WEBP_MIME, GIF_MIME
from calibre.ebooks.oeb.polish.replace import rename_files
from qt.core import QAction, QInputDialog, QProgressDialog, Qt, QTimer, QMessageBox

from calibre_plugins.bulk_img_resizer.ui import ConfigDialog
from calibre_plugins.bulk_img_resizer.image import compress_image


def get_image_type(data):
    if len(data) < 12:
        return None
    
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return 'gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'webp'
    return None


def replace_extension(file_name, new_extension):
    base_name, _ = os.path.splitext(file_name)
    return base_name + new_extension


class BulkImgReducer(Tool):
    name = 'bulk-img-resizer'
    allowed_in_toolbar = True
    allowed_in_menu = True
    default_shortcut = ('Ctrl+Shift+Alt+R',)

    # RASTER_IMAGES = {JPEG_MIME, PNG_MIME, WEBP_MIME, GIF_MIME}

    def __init__(self):
        self.config = None
        self.job_data = None
        self.pd_timer = QTimer()

    def create_action(self, for_toolbar=True):
        ac = QAction(get_icons('images/icon.png'), 'Bulk Image Resizer', self.gui)  # noqa
        if not for_toolbar:
            self.register_shortcut(ac, self.name, default_keys=self.default_shortcut)
        ac.triggered.connect(self.ask_user)
        return ac

    def ask_user(self):
        if not self.ensure_book(_('You must first open a book in order to compress images.')):
            return

        dialog = ConfigDialog()

        if dialog.exec_() != ConfigDialog.Accepted:
            return

        self.config = dialog.max_resolution, dialog.quality, dialog.encoding_type
        print('CONFIG', self.config)

        self.boss.commit_all_editors_to_container()
        self.boss.add_savepoint('Before: Resizing images')
        self.mimify_images()

    def mimify_images(self):
        container = self.current_container  # The book being edited as a container object
        images = self.get_images_from_collection(container)

        if len(images) == 0:
            dialog = QMessageBox()
            dialog.setText('No images found!')
            return

        progress = self.create_progres_dialog(len(images))
        self.job_data = (images, images.copy(), progress, container)

        self.pd_timer.timeout.connect(self.do_one)
        self.pd_timer.start()

    def get_images_from_collection(self, container):
        images = []
        for name in container.mime_map:
            try:
                with container.open(name) as f:
                    header = f.read(12)
                
                if get_image_type(header):
                    images.append(name)
            except Exception:
                continue
        return images

    def create_progres_dialog(self, image_count):
        progress = QProgressDialog('Resizing images...', _('&Stop'), 0, image_count + 1, self.gui)
        progress.setWindowTitle('Resizing...')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setValue(0)
        progress.show()
        return progress

    def do_one(self):
        images, all_images, progress, container = self.job_data
        max_resolution, quality, encoding_type = self.config
        if len(images) == 0 or progress.wasCanceled():
            self.pd_timer.stop()
            self.do_end()
            return
        name = images.pop()
        try:
            # Use raw_data to ensure we get bytes, especially for extensionless files
            # that Calibre might misclassify as text.
            new_image = compress_image(container.raw_data(name), max_resolution, quality, encoding_type)
            container.replace(name, new_image)
        except Exception:
            import traceback
            warning_dialog(self.gui,
                           _('Image Resize Failed'),
                           _(f'The image "{name}" could not be resized. It may be corrupted or in an unsupported format.'),
                           det_msg=traceback.format_exc(), show=True)
        index = len(all_images) - len(images)
        progress.setValue(index)

    def do_end(self):
        _, _, encoding_type = self.config
        _, all_images, progress, container = self.job_data

        progress.setWindowTitle('Renaming files...')
        replace_map = {}
        for name in all_images:
            if encoding_type == 'WebP':
                value = replace_extension(name, '.webp')
            elif encoding_type == 'JPEG':
                value = replace_extension(name, '.jpg')
            elif encoding_type == 'PNG':
                value = replace_extension(name, '.png')
            else:
                break

            if name != value:
                replace_map[name] = value

        rename_files(container, replace_map)

        progress.setValue(len(all_images) + 1)

        self.boss.show_current_diff()
        self.boss.apply_container_update_to_gui()

    def ensure_book(self, msg=None):
        msg = msg or _('No book is currently open. You must first open a book.')
        if current_container() is None:
            error_dialog(self.gui, _('No book open'), msg, show=True)
            return False
        return True
