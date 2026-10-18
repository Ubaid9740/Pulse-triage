// Payload builders for each phone packet kind (shared/schemas/payloads/*.schema.json).
// Only fields the schemas allow; empty optional fields are left out.

const clean = (obj) => Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined && v !== ""));

export function reportPayload({ hazard, forWhom, people, conditions, details, note, lat = null, lng = null,
  accuracy = null, landmark, role = "helper", contact, alertId, registryId }) {
  return clean({
    hazard, for_whom: forWhom, people, conditions, details, note: note?.slice(0, 500), lat, lng,
    gps_accuracy_m: accuracy, landmark: landmark?.slice(0, 200), reporter_role: role === "helper" ? "helper" : role,
    contact, alert_id: alertId, registry_id: registryId,
  });
}

export const alertReply = ({ alertId, status, registryId, lat = null, lng = null }) =>
  clean({ alert_id: alertId, status, registry_id: registryId, lat, lng });

export const welfareCheck = ({ result, registryId, landmark, note, lat = null, lng = null }) =>
  clean({ result, registry_id: registryId, landmark, note, lat, lng });

export const volunteerSetup = ({ name, role, teamType, skills = [], vehicle, lat = null, lng = null }) =>
  clean({ name, role, team_type: teamType, skills, vehicle, lat, lng });

export const ack = ({ teamId, jobId = null, status, outcome, reason }) =>
  clean({ team_id: teamId, job_id: jobId, status, outcome, reason });

export const teamPing = ({ teamId, lat, lng, accuracy = null, status, caseId = null, battery = null, fuel = null }) =>
  ({ team_id: teamId, lat, lng, gps_accuracy_m: accuracy, at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
     status, case_id: caseId, battery, fuel });
