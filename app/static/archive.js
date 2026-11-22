const form = document.querySelector('#case-form');
const filing = document.querySelector('#filing');
const repeat = document.querySelector('#repeat');
const download = document.querySelector('#digest-link');
let filed;

async function file(retain) {
  const submit = form.querySelector('button');
  repeat.disabled = submit.disabled = true;
  filing.textContent = '正在整理案卷…';
  try {
    const response = await fetch(retain ? `/api/runs/${filed}/rerun` : '/api/runs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: retain ? undefined : JSON.stringify({sample: form.dataset.current}),
    });
    const record = await response.json();
    if (!response.ok) throw new Error(record.message);
    filed = record.id;
    filing.textContent = `${record.reused ? '归档一致' : '案卷已归档'} · ${filed.slice(0, 10)}`;
    download.href = `/api/runs/${filed}/export`;
    repeat.hidden = download.hidden = false;
    // 归档后即可在采纳签核页直接形成签核卷。
    const scopeForm = document.querySelector('#signoff-scope');
    if (scopeForm) {
      scopeForm.dataset.run = filed;
      const commit = document.querySelector('#signoff-commit');
      commit.disabled = false;
      commit.removeAttribute('title');
    }
  } catch (error) {
    filing.textContent = error.message || '案卷归档失败。';
  } finally {
    repeat.disabled = submit.disabled = false;
  }
}

form.addEventListener('submit', event => { event.preventDefault(); file(false); });
repeat.addEventListener('click', () => file(true));
