from aiohttp import web
import asyncio
from urllib.parse import quote, unquote
from os import listdir
from os.path import isfile, join
import ebooklib
from ebooklib import epub
import zipfile
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
                #system-clock
                {
                    color: #121212;
                    position:sticky;
                    top:5px;
                    padding-left: 85%;
                    width: 10%;
                    z-index: -1;
                    font-size: 140%;
                    margin: -10px;
                    font-family: monospace, monospace;
                }
            </style>
        </head>
        <script>
            var sc = null;
            var hour = 0;
            var minu = 0;
            function init()
            {
                sc = document.getElementById("system-clock");
                setInterval(clock, 1000);
                clock();
            }
            function clock()
            {
                const now = new Date();
                if(now.getHours() != hour || now.getMinutes() != minu)
                    sc.innerHTML = JSON.stringify(now.getHours()).padStart(2, "0") + ":" + JSON.stringify(now.getMinutes()).padStart(2, "0");
                hour = now.getHours();
                minu = now.getMinutes();
            }
        </script>
        <body onload="init()">
            <div id="system-clock">.</div>
            BODY
        </body>
    </html>
    """
    EPUB_TYPE = 0
    ARCHIVE_TYPE = 1
    # used to detect img links
    IMGRE = re.compile('(src|xlink:href)="([a-zA-Z0-9\/\-\.\_%]+\.(jpg|png|jpeg|gif))')
    def __init__(self):
        print("EPUBServer v1.9")
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
        try: fs = [f for f in listdir(self.folder) if (isfile(join(self.folder, f)) and "." in f and f.split('.')[-1] in ["epub", "zip", "cbz"])]
        except: fs = []
        blist = ""
        if len(fs) == 0:
            blist = '<div class="epub_content">No <b>.epub</b> files in the server folder</div>'
        else:
            bookmarks = {}
            for f in fs:
                if f in self.bookmarks:
                    bookmarks[f] = self.bookmarks[f]
                blist += '- <a href="/read?file={}{}">{}</a><br>'.format(quote(f), '' if self.password is None else "&pass={}".format(quote(self.password)), f.replace('.epub', ''))
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

    def clean_book_cache(self):
        # clear cache
        keys = list(self.loaded.keys())
        if len(keys) >= self.loaded_book_limit:
            n_keys = keys[-self.loaded_book_limit:]
            for k in keys:
                if k not in n_keys:
                    self.loaded.pop(k, None)

    def loadEpub(self, file): # load book into memory
        try:
            book = epub.read_epub(self.folder + '/' + file)
            self.clean_book_cache()
            # load
            spine = book.spine
            self.loaded[file] = {'type':self.EPUB_TYPE, 'pages':[], 'img':{}, 'index':{}}
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

    def formatEpub(self, file, content): # format epub content. NOTE: Don't want to use/include beautifulsoup
        # remove html body tags
        a = 0
        b = 0
        while True:
            a = content.find("<body", b)
            if a == -1:
                break
            else:
                b = content.find(">", a+1)
                if b == -1:
                    pass
                else:
                    content = content[:a] + content[b+1:]
                    b = a
        content = content.replace("</body>", "")
        # tweak badly formed div
        divc = 0
        a = 0
        b = 0
        while True: # count <div> while removing <div/>
            a = content.find("<div", b)
            if a == -1:
                break
            else:
                b = content.find(">", a+1)
                if b == -1:
                    break
                else:
                    if content[b-1] != "/": divc += 1
                    else:
                        content = content[:a] + content[b+1:]
                        b = a
        divc -= content.count("</div>")
        while divc > 0:
            content += "\n</div>"
            divc -= 1
        while divc < 0:
            content += "<div>\n"
            divc += 1
        
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
                content = content[:a] + '<img src="/asset?file={}&path={}">'.format(quote(file), quote(unquote(i[1].split('/')[-1]))) + content[b+6:]
            else:
                content = content.replace(i[1], '/asset?file={}&path={}'.format(quote(file), quote(unquote(i[1].split('/')[-1]))))
        return content

    def loadArchiveContent(self, file): # load zip archive file list
        try:
            self.clean_book_cache()
            with zipfile.ZipFile(self.folder + '/' + file, mode='r') as z:
                namelist = z.namelist()
                self.loaded[file] = {'type':self.ARCHIVE_TYPE, 'pages':namelist, 'img':{}, 'index':{}}
        except Exception as e:
            print("Couldn't load archive:", file)
            print("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise web.HTTPInternalServerError()

    def loadArchiveImage(self, file, img): # load one image
        try:
            keys = list(self.loaded[file]['img'].keys())
            if img not in keys:
                if len(keys) >= 10:
                    keys = keys[5:] # keep 5 latest loaded images
                    self.loaded[file]['img'] = {k:self.loaded[file]['img'][k] for k in keys}
                with zipfile.ZipFile(self.folder + '/' + file, mode='r') as z:
                    with z.open(img) as f:
                        self.loaded[file]['img'][img] = f.read()
            else:
                self.loaded[file]['img'][img] = self.loaded[file]['img'].pop(img) # move at end (to be considered most recently used)
        except Exception as e:
            print("Couldn't load archive content:", file, img)
            print("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise web.HTTPInternalServerError()

    def generateHeaderFooter(self, file, page, count): # make page header/footer
        footer = '<div class="elem">'
        if page > 0: footer += '<a href="/read?file={}&page={}{}">Previous</a> # '.format(quote(file), page-1, '' if self.password is None else "&pass={}".format(quote(self.password)))
        footer += '<a href="/{}">Back</a> # {} / {}'.format('' if self.password is None else "pass={}".format(quote(self.password)), page+1, count)
        if page < count - 1: footer += ' # <a href="/read?file={}&page={}{}">Next</a>'.format(quote(file), page+1, '' if self.password is None else "&pass={}".format(quote(self.password)))
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
            ext = file.split('.')[-1]
            match ext:
                case "epub":
                    self.loadEpub(file)
                case "zip"|"cbz":
                    self.loadArchiveContent(file)
        
        match self.loaded[file]["type"]:
            case self.EPUB_TYPE:
                if not isinstance(self.loaded[file]['pages'][page], str):
                    self.loaded[file]['pages'][page] = self.formatEpub(file, self.loaded[file]['pages'][page].get_body_content().decode("utf-8"))
                content = self.loaded[file]['pages'][page]
            case self.ARCHIVE_TYPE:
                self.loadArchiveImage(file, self.loaded[file]['pages'][page])
                content = '<img src="/asset?file={}&path={}">'.format(quote(file), quote(self.loaded[file]['pages'][page]))
        footer = self.generateHeaderFooter(file, page, len(self.loaded[file]['pages']))
        
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