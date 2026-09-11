/* Every call to the backend lives here.
   Keeping them together means the endpoint list is one screen long, and nothing
   in app.js builds a URL of its own. */

const API = {
  /* Returns { ok, data } rather than throwing, because a rejected scan still
     carries a message the user needs to see. */
  async createScan(body){
    const response = await fetch('/api/scans/create/', {method:'POST', body});
    return {ok: response.ok, data: await response.json()};
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