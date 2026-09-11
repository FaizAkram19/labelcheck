/* Every call to the backend lives here.
   Keeping them together means the endpoint list is one screen long, and nothing
   in app.js builds a URL of its own. */

const API = {
  /* XMLHttpRequest rather than fetch, because only XHR reports upload bytes -
     and on a phone over venue wifi the upload is a real part of the wait.
     Returns { ok, data } rather than throwing, because a rejected scan still
     carries a message the user needs to see. */
  createScan(body, onUploadProgress){
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/scans/create/');
      if(onUploadProgress && xhr.upload){
        xhr.upload.addEventListener('progress', e => {
          if(e.lengthComputable) onUploadProgress(e.loaded / e.total);
        });
      }
      xhr.addEventListener('load', () => {
        let data;
        try{
          data = JSON.parse(xhr.responseText);
        }catch(err){
          reject(new Error('The server sent a reply the app could not read.'));
          return;
        }
        resolve({ok: xhr.status >= 200 && xhr.status < 300, data});
      });
      xhr.addEventListener('error', () => reject(new Error('Network error.')));
      xhr.addEventListener('abort', () => reject(new Error('Upload cancelled.')));
      xhr.send(body);
    });
  },

  async scan(id){
    const response = await fetch('/api/scans/' + id + '/');
    if(!response.ok) throw new Error('Check #' + id + ' could not be loaded.');
    return response.json();
  },

  async history(){
    const response = await fetch('/api/scans/');
    if(!response.ok) throw new Error('History could not be loaded.');
    return response.json();
  },

  async rules(){
    const response = await fetch('/api/rules/');
    if(!response.ok) throw new Error('Rule catalogue could not be loaded.');
    return response.json();
  },

  async health(){
    const response = await fetch('/api/health/');
    if(!response.ok) throw new Error('Health check failed.');
    return response.json();
  },
};