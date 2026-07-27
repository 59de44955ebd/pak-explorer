import brotli
import gzip
import os
import shutil
import sys
import traceback

APP_NAME = 'PAK Explorer'
APP_VERSION = '0.1'
APP_DIR = os.path.dirname(__file__)
IS_FROZEN = getattr(sys, 'frozen', False)

if not IS_FROZEN:
    # Force local imports
    sys.path.append(APP_DIR)

from winapp.const import *
from winapp.controls.edit import *
from winapp.controls.listbox import *
from winapp.controls.statusbar import *
from winapp.dialogs import *
from winapp.dlls import *
from winapp.mainwin import *

from resources import *
from command import *

if IS_FROZEN:
    HMOD_RESOURCES = kernel32.GetModuleHandleW(None)
else:
    HMOD_RESOURCES = kernel32.LoadLibraryW(os.path.join(APP_DIR, '..', 'resources.dll'))

BIN = os.path.join(APP_DIR, 'chrome-pak-customizer.exe')

HCURSOR_ARROW = user32.LoadCursorW(None, IDC_ARROW)
HCURSOR_WAIT = user32.LoadCursorW(None, IDC_WAIT)

# CONFIG
LISTBOX_WIDTH = 140
BLOCK_WIDTH = 16
MAX_BLOCKS = 400


########################################
#
########################################
class App(MainWin):

    ########################################
    #
    ########################################
    def __init__(self):

        self.tmp_dir = None
        self.current_chunk = None
        self.is_edge = False

        self.COMMAND_MESSAGE_MAP = {
            IDM_OPEN:                   self.open_pak_file,
            IDM_SAVE:                   self.save_pak_file,
            IDM_CLOSE:                  self.close_pak_file,
            IDM_EXIT:                   self.quit,
            IDM_ABOUT:                  self.about,
        }

        super().__init__(
            window_title = APP_NAME,
            h_accel = user32.LoadAcceleratorsW(HMOD_RESOURCES, MAKEINTRESOURCEW(1)),
            h_icon = user32.LoadIconW(HMOD_RESOURCES, MAKEINTRESOURCEW(1)),
            h_menu = user32.LoadMenuW(HMOD_RESOURCES, MAKEINTRESOURCEW(1)),
            h_cursor = 0
        )

        user32.SetCursor(HCURSOR_ARROW)

        self.h_menu_listbox = user32.GetSubMenu(user32.LoadMenuW(HMOD_RESOURCES, MAKEINTRESOURCEW(ID_POPUP_MENU_SHOW_FOLDER)), 0)

        self.listbox = ListBox(
            self,
            left = 5,
            width = LISTBOX_WIDTH,
            style = WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOINTEGRALHEIGHT | LBS_NOTIFY| LBS_HASSTRINGS,
        )

        self.listbox.set_font('Segoe UI', -13)
        self.listbox.hide_focus_rects()

        ########################################
        #
        ########################################
        def _on_WM_CONTEXTMENU(hwnd, wparam, lparam):
            x, y = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
            pt = POINT(x, y)
            user32.MapWindowPoints(None, self.listbox.hwnd, byref(pt), 1)
            idx = self.listbox.send_message(LB_ITEMFROMPOINT, 0, MAKELPARAM(pt.x, pt.y))
            if idx < 0:
                return
            res = user32.TrackPopupMenuEx(self.h_menu_listbox, TPM_LEFTBUTTON | TPM_RETURNCMD, x, y, self.hwnd, 0)
            if res == IDM_SHOW_IN_FOLDER:
                buf = create_unicode_buffer(MAX_PATH)
                user32.SendMessageW(self.listbox.hwnd, LB_GETTEXT, idx, buf)
                exec_info = SHELLEXECUTEINFOW()
                exec_info.nShow = SW_SHOWNORMAL
                exec_info.lpFile = 'explorer.exe'
                exec_info.lpParameters = f'/select,"{buf.value}"'
                exec_info.lpDirectory = self.tmp_dir
                shell32.ShellExecuteExW(byref(exec_info))

        self.listbox.register_message_callback(WM_CONTEXTMENU, _on_WM_CONTEXTMENU)

        self.edit = Edit(
            self,
            left = LISTBOX_WIDTH + 5,
            style = WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_WANTRETURN | ES_READONLY,
        )

        self.edit.set_font('Consolas', 11)
        user32.SendMessageW(self.edit.hwnd, EM_SETLIMITTEXT, 0xffffffff, 0)

        self.statusbar = StatusBar(self)

        ########################################
        #
        ########################################
        def _on_WM_SIZE(hwnd, wparam, lparam):
            width, height = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
            self.statusbar.update_size()
            height -= self.statusbar.height
            self.listbox.set_window_pos(
                width = LISTBOX_WIDTH,
                height = height,
                flags = SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
            )
            self.edit.set_window_pos(
                width = width - LISTBOX_WIDTH - 5,
                height = height,
                flags = SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
            )

        self.register_message_callback(WM_SIZE, _on_WM_SIZE)

        ########################################
        #
        ########################################
        def _on_WM_COMMAND(hwnd, wparam, lparam):
            if lparam == 0:
                command_id = LOWORD(wparam)
                if command_id in self.COMMAND_MESSAGE_MAP:
                    self.COMMAND_MESSAGE_MAP[command_id]()

            elif lparam == self.listbox.hwnd:
                code = HIWORD(wparam)

                if code == LBN_SELCHANGE:
                    user32.SetCursor(HCURSOR_WAIT)
                    idx = user32.SendMessageW(self.listbox.hwnd, LB_GETCURSEL, 0, 0)
                    buf = create_unicode_buffer(MAX_PATH)
                    user32.SendMessageW(self.listbox.hwnd, LB_GETTEXT, idx, buf)
                    chunk_name = buf.value
                    self.current_chunk = chunk_name

                    if chunk_name.endswith('.br'):
                        with open(os.path.join(self.tmp_dir, chunk_name), 'rb') as f:
                            data = brotli.decompress(f.read())
                            self.show_data(data)

                    elif chunk_name.endswith('.gz'):
                        with gzip.open(os.path.join(self.tmp_dir, chunk_name), 'rb') as f:
                            self.show_data(f.read())

                    else:
                        with open(os.path.join(self.tmp_dir, chunk_name), 'rb') as f:
                            self.show_data(f.read())
                    user32.SetCursor(HCURSOR_ARROW)

                elif code == LBN_DBLCLK:
                    idx = user32.SendMessageW(self.listbox.hwnd, LB_GETCURSEL, 0, 0)
                    buf = create_unicode_buffer(MAX_PATH)
                    user32.SendMessageW(self.listbox.hwnd, LB_GETTEXT, idx, buf)
                    chunk_name = buf.value
                    if chunk_name.lower().endswith('.png'):
                        exec_info = SHELLEXECUTEINFOW()
                        exec_info.nShow = SW_SHOWNORMAL
                        exec_info.lpFile = os.path.join(self.tmp_dir, chunk_name)
                        shell32.ShellExecuteExW(byref(exec_info))

            elif lparam == self.edit.hwnd:
                code = HIWORD(wparam)
                if code == EN_CHANGE:
                    buf_size = user32.SendMessageW(self.edit.hwnd, WM_GETTEXTLENGTH, 0, 0) + 1
                    buf = create_unicode_buffer(buf_size)
                    user32.SendMessageW(self.edit.hwnd, WM_GETTEXT, buf_size, buf)
                    text = buf.value.replace('\r\n', '\n')
                    with open(os.path.join(self.tmp_dir, self.current_chunk + '.txt'), 'w', newline='\n') as f:
                        f.write(text)

        self.register_message_callback(WM_COMMAND, _on_WM_COMMAND)

        ########################################
        #
        ########################################
        def _on_WM_DROPFILES(hwnd, wparam, lparam):
            dropped_items = self.get_dropped_items(wparam)
            if os.path.isfile(dropped_items[0]) and dropped_items[0].lower().endswith('.pak'):
                self.load_pak_file(dropped_items[0])

        self.register_message_callback(WM_DROPFILES, _on_WM_DROPFILES)

        self.show()

        shell32.DragAcceptFiles(self.hwnd, TRUE)

    ########################################
    #
    ########################################
    def open_pak_file(self):
        pak_file = show_open_file_dialog(
            hwnd = self.hwnd,
            filter_string = 'PAK Files (*.pak)\0*.pak\0\0',
            initial_path = 'resources.pak'
        )
        if pak_file:
            self.load_pak_file(pak_file)

    ########################################
    #
    ########################################
    def load_pak_file(self, pak_file):
        self.reset_ui()

        user32.SetWindowTextW(self.statusbar.hwnd, '  Loading PAK file...')
        user32.SetCursor(HCURSOR_WAIT)

        if self.tmp_dir:
            shutil.rmtree(self.tmp_dir)

        self.tmp_dir = os.path.join(APP_DIR, 'tmp')

        self.is_edge = False
        command = f'"{BIN}" -u "{pak_file}" "{self.tmp_dir}"'
        out, err, exit_code = run_command(command)
#        print(out, err, exit_code)

        if exit_code != 0:
            self.is_edge = True
            command = f'"{BIN}" -e -u "{pak_file}" "{self.tmp_dir}"'
            out, err, exit_code = run_command(command)

        if exit_code != 0:
            user32.SetWindowTextW(self.statusbar.hwnd, out.decode())
            return

        user32.SendMessageW(self.listbox.hwnd, WM_SETREDRAW, FALSE, 0)

        chunks = os.listdir(self.tmp_dir)

        chunks.remove('pak_index.ini')
        user32.SendMessageW(self.listbox.hwnd, LB_ADDSTRING, 0, 'pak_index.ini')

        chunks.sort(key = lambda x: int(x.split('.')[0]))
        for f in chunks:
            user32.SendMessageW(self.listbox.hwnd, LB_ADDSTRING, 0, f)

        user32.SendMessageW(self.listbox.hwnd, WM_SETREDRAW, TRUE, 0)
        user32.EnableMenuItem(self.h_menu, IDM_CLOSE, MF_ENABLED)
        user32.EnableMenuItem(self.h_menu, IDM_SAVE, MF_ENABLED)

        user32.SetWindowTextW(self.hwnd, f'{pak_file} - {APP_NAME}')

        user32.SetWindowTextW(self.statusbar.hwnd, '')
        user32.SetCursor(HCURSOR_ARROW)

    ########################################
    #
    ########################################
    def save_pak_file(self):
        pak_file = show_save_file_dialog(
            hwnd = self.hwnd,
            filter_string = 'PAK Files\0*.pak\0\0',
            initial_path = 'resources.pak'
        )
        if not pak_file:
            return

        user32.SetWindowTextW(self.statusbar.hwnd, '  Creating new PAK file...')
        user32.SetCursor(HCURSOR_WAIT)

        chunks = os.listdir(self.tmp_dir)
        for chunk_name in chunks:
            if chunk_name.endswith('.br.txt'):
                with open(os.path.join(self.tmp_dir, chunk_name), 'rb') as f:
                    data = brotli.compress(f.read(), quality = 6)
                with open(os.path.join(self.tmp_dir, chunk_name[:-4]), 'wb') as f:
                    f.write(data)

            elif chunk_name.endswith('.gz.txt'):
                with open(os.path.join(self.tmp_dir, chunk_name), 'rb') as f:
                    data = f.read()
                with gzip.open(os.path.join(self.tmp_dir, chunk_name[:-4]), 'wb') as f:
                    f.write(data)

            elif chunk_name.endswith('.txt'):
                with open(os.path.join(self.tmp_dir, chunk_name), 'rb') as f:
                    data = f.read()
                with open(os.path.join(self.tmp_dir, chunk_name[:-4]), 'wb') as f:
                    f.write(data)

        ini_file = os.path.join(self.tmp_dir, 'pak_index.ini')
        if self.is_edge:
            command = f'"{BIN}" -e -p "{ini_file}" "{pak_file}"'
        else:
            command = f'"{BIN}" -p "{ini_file}" "{pak_file}"'
        out, err, exit_code = run_command(command)
#        print(out, err, exit_code)

        user32.SetCursor(HCURSOR_ARROW)
        user32.SetWindowTextW(self.statusbar.hwnd, out.decode() if exit_code != 0 else '')

    ########################################
    #
    ########################################
    def close_pak_file(self):
        if self.tmp_dir:
            user32.SetWindowTextW(self.statusbar.hwnd, '  Clearing temporary files...')
            user32.SetCursor(HCURSOR_WAIT)
            shutil.rmtree(self.tmp_dir)
            self.tmp_dir = None
            user32.SetWindowTextW(self.statusbar.hwnd, '')
            user32.SetCursor(HCURSOR_ARROW)
        self.reset_ui()

    ########################################
    #
    ########################################
    def reset_ui(self):
        user32.SetWindowTextW(self.hwnd, APP_NAME)
        user32.SendMessageW(self.listbox.hwnd, LB_RESETCONTENT, 0, 0)
        user32.SetWindowTextW(self.edit.hwnd, '')
        user32.SendMessageW(self.edit.hwnd, EM_SETREADONLY, TRUE, 0)
        user32.EnableMenuItem(self.h_menu, IDM_CLOSE, MF_GRAYED)
        user32.EnableMenuItem(self.h_menu, IDM_SAVE, MF_GRAYED)
        user32.SetWindowTextW(self.statusbar.hwnd, '')

    ########################################
    #
    ########################################
    def show_data(self, data):
        try:
            user32.SetWindowTextW(self.edit.hwnd, data.decode().replace('\n', '\r\n'))
            user32.SendMessageW(self.edit.hwnd, EM_SETREADONLY, FALSE, 0)
        except:
            data_show = data[:MAX_BLOCKS * BLOCK_WIDTH]
            rows = [data_show[i:i + BLOCK_WIDTH] for i in range(0, len(data_show), BLOCK_WIDTH)]
            lines = [self.hex_line(lineno, row) for lineno, row in enumerate(rows)]
            missing = len(data) - len(data_show)
            if missing:
                lines.append(f'\r\n--> Data display truncated, {missing} more bytes.')
            user32.SetWindowTextW(self.edit.hwnd, '\r\n'.join(lines))
            user32.SendMessageW(self.edit.hwnd, EM_SETREADONLY, TRUE, 0)

    ########################################
    #
    ########################################
    def hex_line(self, lineno, row):
        return (
            hex(lineno * BLOCK_WIDTH)[2:].zfill(8) +
            'h: ' +
            ''.join(f'{byte:02X} ' for byte in row) +
            '   ' * (BLOCK_WIDTH - len(row)) +
            '; ' +
            ''.join(chr(byte) if 0x20 <= byte < 0x7F else '.' for byte in row)
        )

    ########################################
    #
    ########################################
    def about(self):
        show_message_box(
            self.hwnd,
            (
                f'{APP_NAME} v{APP_VERSION}\n\n'
                'A simple tool for exploring and editing text resources in Chrome/Chromium/Edge/WebView2 PAK files.\n\n'
                f'{APP_NAME} is based on chrome-pak-customizer:\n'
                'https://github.com/myfreeer/chrome-pak-customizer'
            ),
            'About'
        )

    ########################################
    #
    ########################################
    def quit(self, *_):
        if self.tmp_dir:
            user32.SetWindowTextW(self.statusbar.hwnd, '  Clearing temporary files...')
            user32.SetCursor(HCURSOR_WAIT)
            shutil.rmtree(self.tmp_dir)
        super().quit()


########################################
#
########################################
if __name__ == '__main__':
    sys.excepthook = traceback.print_exception
    sys.exit(App().run())
