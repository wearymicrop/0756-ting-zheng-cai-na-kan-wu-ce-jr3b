const form = document.querySelector('#signoff-scope');
if (form) {
  const state = document.querySelector('#signoff-state');
  const button = document.querySelector('#signoff-commit');
  const boxes = Array.from(form.querySelectorAll('input[name=scope]'));

  function selected() {
    return boxes.filter(box => box.checked).map(box => box.value);
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.dataset.run) {
      state.textContent = '请先归档案卷，再形成签核卷。';
      return;
    }
    const scope = selected();
    if (!scope.length) {
      state.textContent = '至少勾选一支末版作为采用范围。';
      return;
    }
    button.disabled = true;
    state.textContent = '正在形成签核卷…';
    fetch(`/api/runs/${form.dataset.run}/signoff`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({scope}),
    }).then(async response => {
      const volume = await response.json();
      if (!response.ok) throw new Error(volume.message || '签核失败');
      const url = new URL(window.location.href);
      url.searchParams.set('run', volume.run_id);
      window.location.assign(url.href);
    }).catch(error => {
      state.textContent = error.message || '签核失败。';
      button.disabled = false;
    });
  });
}
