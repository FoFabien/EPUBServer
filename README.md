# EPUBServer
Simple Python Server to read EPUB files from any device (computer, phone, etc...) on the same network using a web browser.  
It also supports CBZ and ZIP files containing images.  
PDF are NOT supported.

### Installation
1. [Python](https://www.python.org/downloads/) must be installed on the device acting like the server. It has been tested with Python 3.11.
2. The following third party modules must be installed via a command prompt or terminal `python -m pip install aiohttp ebooklib`

### Usage
Double click `epubserver.py` or start it via a command prompt or terminal using `python epubserver.py`.  
To stop the server, do a `CTRL+C`.  
Make a folder named `books` alongside the file and put your `.epub`, `.cbz` and `.zip` files in it. Sub-folder aren't currently supported.  
Then go to `http://localhost:8000` if you're on the same machine (replace localhost by its IP otherwise).  

### Settings
`settings.json` will be created after using it (or you can create it yourself).  
Here's a list of the variables you'll find inside:  
- `password`: **null** is the default value but you can put whatever string you want to protect your server access. Add it to the url to authentificate yourself, example: `http://localhost:8000/?pass=My_password`.
- `folder`: **"books"** is the default value but you can set whatever path you want here, if your files are located in another place.  
- `loaded_book_limit`: **4** is the default value. The maximum number of books loaded at the same time in memory.  
- `bookmarks`: This is automatically managed by the server, you shouldn't have to touch it. It's used to memorize the last viewed part of an epub, for a quick resume.
  
### Disclaimer
This application was designed to be used at home, in a safe local environment.  
Little consideration has been put towards security, I wouldn't recommend using it over the Internet. Keep your usage for a local or your home private network.  
If you do, at least set a password but keep in mind the password isn't transmitted in a secure-way either.  
If you have the know-how, you can also try to add HTTPS support to it.  
The above statements are subject to change in future versions.  
