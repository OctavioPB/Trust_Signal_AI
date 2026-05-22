# Data Processing Agreement (DPA)
**TrustSignal AI — Beta Customer Template**

*Version 1.0 · Effective: [DATE]*

---

## Parties

| Role | Party |
|------|-------|
| **Data Controller** | [CUSTOMER LEGAL NAME], registered at [ADDRESS] ("**Customer**") |
| **Data Processor** | TrustSignal AI (operated by Octavio Pérez Bravo, "**TrustSignal**") |

This Data Processing Agreement ("DPA") supplements the TrustSignal AI Service Agreement and governs the processing of Personal Data by TrustSignal on behalf of the Customer in connection with the TrustSignal interview authenticity scoring service ("**Service**").

---

## 1. Definitions

| Term | Meaning |
|------|---------|
| **Personal Data** | Any information relating to an identified or identifiable natural person ("data subject"), as defined in GDPR Article 4(1). |
| **Processing** | Any operation performed on Personal Data (collection, storage, analysis, deletion). |
| **Sub-processor** | Any third party engaged by TrustSignal to process Personal Data. |
| **Interview Session** | A single audio-recorded candidate interview processed by the Service. |

---

## 2. Scope of Processing

### 2.1 Categories of Data Subjects
- Job candidates participating in recorded interviews

### 2.2 Categories of Personal Data Processed

| Category | Description | Retention |
|----------|-------------|-----------|
| Audio recordings | Raw PCM audio of interview sessions | **90 days** — auto-deleted via lifecycle policy |
| Transcripts | Machine-generated text transcripts of interviews | **90 days** — deleted with session data |
| Session metadata | Timestamps, session UUIDs, TrustScore, signal breakdowns | Duration of service agreement |

> **No Sensitive Data**: TrustSignal does not collect or process special-category data (GDPR Article 9) such as health information, ethnicity, or political opinions.

### 2.3 Purpose of Processing
TrustSignal processes Personal Data solely to:
1. Compute a TrustScore (0–100) indicating interview authenticity
2. Deliver signal breakdowns and reports to the Customer's authorised recruiters
3. Retrain internal fraud-detection models on anonymised, aggregated patterns (no individual re-identification)

---

## 3. Data Controller Obligations

The Customer agrees to:
- Obtain valid, informed consent from candidates before recording begins (or rely on a lawful basis under GDPR Article 6)
- Provide candidates with a privacy notice describing TrustSignal's processing
- Not instruct TrustSignal to process data in a manner that violates applicable law
- Notify TrustSignal promptly of any data subject rights requests

---

## 4. Data Processor Obligations (TrustSignal)

TrustSignal agrees to:

### 4.1 Instructions
Process Personal Data only on documented instructions from the Customer, unless required by EU/Member State law.

### 4.2 Confidentiality
Ensure all personnel authorised to process Personal Data are bound by confidentiality obligations.

### 4.3 Security (GDPR Article 32)

| Control | Implementation |
|---------|---------------|
| Pseudonymisation | All internal identifiers are UUIDs; no names or emails in logs or Kafka payloads |
| Encryption in transit | TLS 1.2+ for all API endpoints and data streams |
| Encryption at rest | AES-256 for audio objects in MinIO / S3 |
| Access control | JWT-authenticated API; recruiter tokens scoped to their organisation |
| Audit logging | Structured JSON logs (structlog); session UUIDs only — no PII |
| Automated deletion | MinIO 90-day lifecycle policy enforced on the `raw-audio` bucket |

### 4.4 Sub-processors

| Sub-processor | Role | Location |
|---------------|------|----------|
| AWS S3 (production) | Audio and artefact storage | EU-WEST-1 (Ireland) |
| OpenAI (optional, opt-in) | Cloud Whisper STT fallback | US — Standard Contractual Clauses apply |

TrustSignal will notify the Customer at least 30 days before engaging a new sub-processor. The Customer has the right to object.

### 4.5 Data Subject Rights Assistance
TrustSignal will assist the Customer in responding to data subject rights requests by:
- Providing a `DELETE /session/{session_id}` API endpoint that immediately wipes audio objects and in-memory session state
- Completing Delta Lake transcript deletion within 24 hours via the nightly retraining DAG

### 4.6 Data Breach Notification
TrustSignal will notify the Customer within **72 hours** of becoming aware of a Personal Data breach affecting Customer data, providing: nature of the breach, categories and approximate number of data subjects affected, likely consequences, and measures taken.

### 4.7 Data Protection Impact Assessment
TrustSignal will provide reasonable assistance to the Customer for any DPIA (GDPR Article 35) related to the Service.

---

## 5. International Data Transfers

Audio data is stored in [EU-WEST-1 / specify region]. Any transfer outside the EEA uses:
- Standard Contractual Clauses (SCCs) approved by the European Commission (2021/914)
- Or an adequacy decision under GDPR Article 45

---

## 6. Audit Rights

The Customer may, upon 30 days' written notice and at its own cost, audit TrustSignal's compliance with this DPA no more than once per year. TrustSignal may satisfy this right by providing a current ISO 27001 certificate or equivalent third-party audit report.

---

## 7. Deletion and Return of Data

Upon termination of the Service Agreement:
- All audio data is deleted within **90 days** (or immediately if requested)
- Anonymised, aggregated model weights derived from Customer data are retained for fraud-detection model integrity
- Customer may request a certified deletion confirmation within 30 days of termination

---

## 8. Duration and Governing Law

This DPA is effective for the duration of the Service Agreement.

Governing law: **[JURISDICTION]** (default: laws of the European Union and applicable Member State law).

---

## 9. Signatures

| | Customer | TrustSignal AI |
|-|----------|----------------|
| **Name** | | Octavio Pérez Bravo |
| **Title** | | Founder & Data & AI Strategy Architect |
| **Date** | | |
| **Signature** | | |

---

*This template is provided for informational purposes. Customers should have this agreement reviewed by qualified legal counsel before execution.*
