/* Cache only the public shell. Authenticated API results and commands are never cached. */
const CACHE='omnilink-client-v0.6.0';
const SHELL=['/client/','/client/assets/style.css','/client/assets/widgets.css','/client/assets/app.js','/client/assets/widgets.js','/client/assets/flows.js','/client/assets/pwa.js','/client/assets/manifest.webmanifest','/client/assets/icons/icon-192.png','/client/assets/icons/icon-512.png'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)));});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('omnilink-client-')&&key!==CACHE).map(key=>caches.delete(key)))));});
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||!SHELL.includes(url.pathname))return;
  event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(event.request,copy)));}return response;}).catch(()=>caches.match(event.request)));
});
