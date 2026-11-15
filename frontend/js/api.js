// Thin client for the REST API. Errors carry a readable message and, for engine validation
// failures, the list of individual issues.

export class ApiError extends Error {
  constructor(message, status, issues = []) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

function describe(body, status) {
  if (body && typeof body.detail === "string") return { message: body.detail, issues: body.issues ?? [] };
  if (body && Array.isArray(body.detail)) {
    const issues = body.detail.map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`);
    return { message: "The request was not valid.", issues };
  }
  return { message: `The server answered with status ${status}.`, issues: [] };
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Could not reach the server. Check that it is running and try again.", 0);
  }
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON error body */
  }
  if (!response.ok) {
    const { message, issues } = describe(data, response.status);
    throw new ApiError(message, response.status, issues);
  }
  return data;
}

export const listScenarios = () => request("GET", "/api/scenarios");
export const getScenario = (id) => request("GET", `/api/scenarios/${id}`);
export const listRuns = (id) => request("GET", `/api/scenarios/${id}/runs`);
export const getRun = (id) => request("GET", `/api/runs/${id}`);
export const generate = (preset) => request("POST", "/api/data/generate", { preset });
export const solve = (id, timeLimitSeconds) =>
  request("POST", `/api/scenarios/${id}/solve`, { time_limit_s: timeLimitSeconds });
export const compare = (runA, runB) => request("GET", `/api/compare?run_a=${runA}&run_b=${runB}`);
