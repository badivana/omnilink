'use strict';
let installPrompt=null;
if('serviceWorker' in navigator && window.isSecureContext){
  navigator.serviceWorker.register('/client/sw.js',{scope:'/client/'}).catch(()=>{});
}
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;document.getElementById('install-app').classList.remove('hidden');});
document.getElementById('install-app').onclick=async()=>{
  if(!installPrompt)return;await installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;document.getElementById('install-app').classList.add('hidden');
};
window.addEventListener('appinstalled',()=>{document.getElementById('install-help').textContent='OmniLink is installed on this device.';document.getElementById('install-app').classList.add('hidden');});
if(window.matchMedia('(display-mode: standalone)').matches||navigator.standalone)document.getElementById('install-help').textContent='OmniLink is running as an installed app.';
