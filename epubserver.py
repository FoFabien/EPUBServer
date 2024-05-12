from aiohttp import web
import asyncio
from urllib.parse import quote
from os import listdir
from os.path import isfile, join
import ebooklib
from ebooklib import epub
import re
import mimetypes
import traceback
import json

class EPUBServer():
    # HTML base page
    BASE_HTML = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>EPUB Server</title>
            <style>
                body {
                    background-color: #282c2e
                }
                .elem {
                    border: 2px solid black;
                    display: table;
                    background-color: #b8b8b8;
                    margin: 10px 50px 10px;
                    padding: 10px 10px 10px 10px;
                    font-size: 180%;
                }
                .epub_content
                {
                    color: #c7c7c7;
                    font-size: 150%
                }
                img
                {
                    max-width: 90%;
                }
                :not(.elem) > a
                {
                    background-color: #b8b8b8;
                    margin: 2px;
                }
            </style>
        </head>
        <body>
            BODY
        </body>
    </html>
    """
    # used to detect img links
    IMGRE = re.compile('(src|xlink:href)="([a-zA-Z0-9\/\-\.\_]+\.(jpg|png|jpeg|gif))')
    def __init__(self):
        print("EPUBServer v1.3")
        self.password = None # server password
        self.folder = "books" # server folder
        self.loaded_book_limit = 4 # book limit in memory
        self.modified = False # save data pending flag
        self.bookmarks = {} # bookmark list
        self.load() # loading data...
        self.loaded = {} # loaded book
        self.favicon = None # will contain the server favicon
        self.autosave_task = None # will contain the autosave task
        if self.password is not None:
            print("Server password is:", self.password)
            print("Add to your request url: ?pass={}".format(quote(self.password)))
        if self.folder.endswith('/') or self.folder.endswith('\\'):
            self.folder = self.folder[:-1]
        self.app = web.Application()
        self.app.on_startup.append(self.init_autosave)
        self.app.on_cleanup.append(self.stop_autosave)
        self.app.add_routes([
                web.get('/', self.main),
                web.get('/favicon.ico', self.icon),
                web.get('/read', self.read),
                web.get('/asset', self.asset)
        ])

    # save data ========================================================================
    def load(self):
        try:
            with open('settings.json', mode='r', encoding='utf-8') as f:
                data = json.load(f)
                self.password = data.get('password', None)
                self.folder = data.get('folder', 'books')
                self.loaded_book_limit = data.get('loaded_book_limit', 4)
                self.bookmarks = data.get('bookmarks', {})
        except:
            pass

    def save(self):
        if not self.modified: return
        try:
            with open('settings.json', mode='w', encoding='utf-8') as outfile:
                json.dump({'password': self.password, 'folder': self.folder, 'loaded_book_limit': self.loaded_book_limit, 'bookmarks': self.bookmarks}, outfile, ensure_ascii=False)
        except Exception as e:
            print("Failed to update settings.json:")
            print("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    
    async def autosave(self):
        try:
            while True:
                await asyncio.sleep(120)
                self.save()
        except asyncio.CancelledError:
            pass

    async def init_autosave(self, app):
        self.autosave_task = asyncio.create_task(self.autosave())

    async def stop_autosave(self, app):
        self.autosave_task.cancel()

    # entry point ========================================================================
    def run(self):
        try: web.run_app(self.app, port=8000)
        except: pass
        self.save()

    def permitted(self, request):
        if not (self.password is None or request.rel_url.query.get('pass', '') == self.password):
            raise web.HTTPInternalServerError()

    # handlers ========================================================================
    async def main(self, request):
        self.permitted(request)
        try: fs = [f for f in listdir(self.folder) if (isfile(join(self.folder, f)) and f.endswith('.epub'))]
        except: fs = []
        blist = ""
        if len(fs) == 0:
            blist = '<div class="epub_content">No <b>.epub</b> files in the server folder</div>'
        else:
            bookmarks = {}
            for f in fs:
                if f in self.bookmarks:
                    bookmarks[f] = self.bookmarks[f]
                blist += '<a href="/read?file={}{}">{}</a><br>'.format(quote(f), '' if self.password is None else "&pass={}".format(quote(self.password)), f.replace('.epub', ''))
            blist = '<div class="elem">' + blist + '</div>'
            if len(bookmarks) != len(self.bookmarks):
                self.bookmarks = bookmarks
                self.modified = True
        blist = '<div class="elem"><h3>EPUB Server - File List</h3></div>' + blist
        return web.Response(text=self.BASE_HTML.replace('BODY', blist), content_type='text/html')

    async def icon(self, request):
        if self.favicon is None:
            try:
                with open("favicon.ico", 'rb') as f:
                    self.favicon = f.read()
            except Exception as e:
                print("Failed to load favicon:")
                print("".join(traceback.format_exception(type(e), e, e.__traceback__)))
                raise web.HTTPNotFound()
        return web.Response(body=self.favicon, content_type='image/x-icon')

    def loadEpub(self, file): # load book into memory
        try:
            book = epub.read_epub(self.folder + '/' + file)
            # clear cache
            keys = list(self.loaded.keys())
            if len(keys) >= self.loaded_book_limit:
                n_keys = keys[-self.loaded_book_limit:]
                for k in keys:
                    if k not in n_keys:
                        self.loaded.pop(k, None)
            # load
            spine = book.spine
            self.loaded[file] = {'pages':[], 'img':{}, 'index':{}}
            for s in spine:
                if s[0] is None: continue
                i = book.get_item_with_id(s[0])
                if i.get_type() == ebooklib.ITEM_DOCUMENT:
                    self.loaded[file]['index'][s[0]] = len(self.loaded[file]['pages'])
                    self.loaded[file]['pages'].append(i)
            for i in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                self.loaded[file]['img'][i.get_name().split('/')[-1]] = i.get_content()
            for i in book.get_items_of_type(ebooklib.ITEM_COVER):
                self.loaded[file]['img'][i.get_name().split('/')[-1]] = i.get_content()
        except Exception as e:
            print("Couldn't load book:", file)
            print("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise web.HTTPInternalServerError()

    def formatEpub(self, file, content): # format epub content
        # remove html style
        a = 0
        b = 0
        while True:
            a = content.find("style=\"", b)
            if a == -1:
                break
            else:
                b = a + len("style=\"")
                a = content.find("color:", a)
                if a == -1:
                    pass
                else:
                    a += len("color:")
                    b = content.find(";", a)
                    if b == -1:
                        b = content.find("\"", a)
                    if b == -1:
                        b = a
                    else:
                        content = content[:a] + content[b:]
                        b = a
        # edit link
        a = 0
        b = 0
        c = 0
        while True:
            a = content.find('<a ', b)
            if a == -1:
                break
            else:
                b = content.find("</a>", a)
                c = content.find("/>", a)
                if b == -1 and c == -1:
                    break
                else:
                    if b == -1: b = 9999999999999999
                    if c == -1: c = 9999999999999999
                    if b < c:
                        c = b
                        b += len("</a>")
                    else:
                        b = c + len("/>")
                    bc = content[a:b]
                    mc = bc[bc.find('href="')+len('href="'):bc.find('">')]
                    fc = mc.split('/')[-1]
                    if fc not in self.loaded[file]['index']:
                        if fc.replace('.', '_') in self.loaded[file]['index']: fc = fc.replace('.', '_')
                        else: fc = fc.split('.')[0]
                    if fc in self.loaded[file]['index']:
                        content = content.replace(mc, "/read?file={}&page={}{}".format(quote(file), self.loaded[file]['index'][fc], '' if self.password is None else "&pass={}".format(quote(self.password))))
                        b = a + 1
                    else:
                        if bc.find('">') != -1: content = content[:a] + bc[bc.find('">')+2:c] + content[b:]
                        else: content = content[:a] + content[b:]
                        b = a
        # add images
        r = self.IMGRE.findall(content)
        for i in r:
            if i[0] == 'xlink:href':
                a = content.find('<svg')
                b = content.find('</svg>')
                content = content[:a] + '<img src="/asset?file={}&path={}">'.format(quote(file), quote(i[1].split('/')[-1])) + content[b+6:]
            else:
                content = content.replace(i[1], '/asset?file={}&path={}'.format(quote(file), quote(i[1].split('/')[-1])))
        return content

    def generateHeaderFooter(self, file, page): # make page header/footer
        footer = '<div class="elem">'
        if page > 0: footer += '<a href="/read?file={}&page={}{}">Previous</a> # '.format(quote(file), page-1, '' if self.password is None else "&pass={}".format(quote(self.password)))
        footer += '<a href="/{}">Back</a>'.format('' if self.password is None else "pass={}".format(quote(self.password)))
        if page < len(self.loaded[file]['pages']) - 1: footer += ' # <a href="/read?file={}&page={}{}">Next</a>'.format(quote(file), page+1, '' if self.password is None else "&pass={}".format(quote(self.password)))
        footer += '</div>'
        return footer

    async def read(self, request):
        self.permitted(request)
        file = request.rel_url.query.get('file', None)
        page = int(request.rel_url.query.get('page', self.bookmarks.get(file, 0)))
        self.bookmarks[file] = page
        self.modified = True
        if file is None:
            raise web.HTTPNotFound()
        if file not in self.loaded:
            self.loadEpub(file)
        
        if not isinstance(self.loaded[file]['pages'][page], str):
            self.loaded[file]['pages'][page] = self.formatEpub(file, self.loaded[file]['pages'][page].get_body_content().decode("utf-8"))
        content = self.loaded[file]['pages'][page]
        footer = self.generateHeaderFooter(file, page)
        
        return web.Response(text=self.BASE_HTML.replace('BODY', footer + '<div class="epub_content">' + content + '</div>' + footer), content_type='text/html')

    async def asset(self, request):
        file = request.rel_url.query.get('file', None)
        path = request.rel_url.query.get('path', None)
        if file is None or path is None:
            raise web.HTTPNotFound()
        data = self.loaded.get(file, {'img':{}})['img'].get(path, None)
        if data is None:
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type=mimetypes.guess_type(path, strict=True)[0])

if __name__ == '__main__':
    EPUBServer().run()