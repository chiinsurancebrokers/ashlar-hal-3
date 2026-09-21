(() => {
  window.ashlarFetch = async (url, options = {}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      return await window.fetch(url, {...options, signal: options.signal || controller.signal});
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('This request took too long. Your selections are still here. Please try again.');
      throw new Error('Connection interrupted. Your selections are still here. Please retry; an enquiry may already have been received.');
    } finally { clearTimeout(timer); }
  };
})();
