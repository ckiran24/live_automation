const form = document.querySelector("#job-form");
const submit = document.querySelector("#submit");
const health = document.querySelector("#health");
const message = document.querySelector("#message");
const details = document.querySelector("#details");
let active = false;

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function checkHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    const value = await response.json();
    health.textContent = response.ok ? `API ready · ${value.queued} queued` : "API unavailable";
  } catch {
    health.textContent = "API unavailable";
  }
}

async function pollJob(jobId, token) {
  while (active) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const response = await fetch(`/jobs/${encodeURIComponent(jobId)}`, {
      headers: authHeaders(token), cache: "no-store"
    });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "Could not read job status");
    document.querySelector("#job-status").textContent = job.status;
    document.querySelector("#manifest").textContent = job.manifest || "—";
    document.querySelector("#reused").textContent = job.session_reused === undefined ? "—" : String(job.session_reused);
    if (["succeeded", "failed"].includes(job.status)) {
      message.textContent = job.status === "succeeded" ? "Run completed." : `Run failed (${job.error_type || "see manifest"}).`;
      active = false;
      submit.disabled = false;
      await checkHealth();
      return;
    }
    message.textContent = job.status === "running" ? "The runner is working…" : "Waiting in the queue…";
    await checkHealth();
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (active) return;
  const token = document.querySelector("#token").value.trim();
  const body = {
    portal: document.querySelector("#portal").value.trim(),
    inputs: document.querySelector("#inputs").value.trim(),
    headed: document.querySelector("#headed").checked
  };
  submit.disabled = true;
  message.textContent = "Submitting job…";
  details.hidden = true;
  try {
    const response = await fetch("/jobs", {
      method: "POST",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error === "queue_full" ? "Queue is full; wait and retry." : "Job was not accepted. Check token and project paths.");
    document.querySelector("#job-id").textContent = job.id;
    document.querySelector("#job-status").textContent = job.status;
    document.querySelector("#manifest").textContent = "—";
    document.querySelector("#reused").textContent = "—";
    details.hidden = false;
    message.textContent = "Job queued.";
    active = true;
    await pollJob(job.id, token);
  } catch (error) {
    message.textContent = error instanceof TypeError ? "Could not reach the local API. Is it running?" : error.message;
    submit.disabled = false;
    active = false;
  }
});

checkHealth();
