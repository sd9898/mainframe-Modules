// Sample JavaScript file - handled by the generic parser fallback
const API_URL = "http://localhost:8000";

function analyze(file) {
  return fetch(API_URL + "/analyze", { method: "POST", body: file })
    .then((res) => res.json())
    .catch((err) => console.log("error", err));
}

export default analyze;
