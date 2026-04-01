# n8n Workflow Patterns — Reference Guide

> Reference for building n8n automations that integrate with Wavelength v3.
> Based on the production FWAI Post-Call AI Career Roadmap workflow.

---

## 1. Workflow Structure

### Settings (always include)
```json
{
  "settings": {
    "executionOrder": "v1",
    "binaryMode": "separate"
  }
}
```
- `executionOrder: "v1"` — deterministic top-to-bottom execution
- `binaryMode: "separate"` — required when handling files (PDF, images)

### Node Types Used
| Type | Version | Purpose |
|------|---------|---------|
| `n8n-nodes-base.webhook` | 2 | Entry point — receives POST from Wavelength |
| `n8n-nodes-base.httpRequest` | 4.2 | API calls (Gemini, GCS, WATI, GHL) |
| `n8n-nodes-base.code` | 2 | Data transformation, prompt building, HTML generation |
| `n8n-nodes-base.set` | 3.4 | JSON parsing (Gemini response → structured data) |
| `n8n-nodes-base.if` | 2.1 | Conditional branching |
| `n8n-nodes-base.noOp` | 1 | Dead-end for rejected branches |

### Node Naming Convention
- **Webhook**: Descriptive source name → `Wavelength Webhook`
- **Code nodes**: Descriptive action → `Build HTML Report`, `Build PDF URL`, `Clean GCS Response`
- **HTTP Request**: Action + target → `AI Qualify Lead`, `Upload PDF to GCS`, `Send WhatsApp Roadmap`
- **Conditionals**: Question format → `Is Qualified?`
- **No-ops**: Short label → `Skip`, `Done`

---

## 2. Data Passing Patterns

### Three ways to access data

```javascript
// 1. From the immediately previous node (most common)
$input.first().json        // explicit
$json                      // shorthand (in expressions only)

// 2. From any named node (cross-reference — preferred for non-adjacent)
$('Node Name').item.json          // single item
$('Node Name').first().json       // same thing, more explicit
$('Node Name').all()[0].json      // when you need index access

// 3. In expressions (HTTP Request URL, body fields)
{{ $json.field }}                          // previous node
{{ $('Node Name').item.json.field }}       // named node
```

### Rule of thumb
- **Adjacent node data** → use `$input.first().json` or `$json`
- **Non-adjacent node data** → use `$('Node Name').item.json`
- **Forward data for later nodes** → include in `return [{ json: { ...data } }]`

### Passing data through the chain
```javascript
// Code node: always return array of objects with json key
return [{ json: { requestBody, original_payload: body } }];

// With binary data (for file uploads)
return [{
  json: { uuid, lead_name, lead_phone },
  binary: {
    data: {
      data: binaryData.toString('base64'),
      mimeType: 'text/html',
      fileName: 'index.html'
    }
  }
}];
```

---

## 3. Webhook Payload Handling

### Wavelength webhook payload structure
```json
{
  "event": "post_call",
  "automation_id": "...",
  "automation_name": "...",
  "timestamp": "2026-03-31T11:18:39Z",
  "wavelength_version": "v3",
  "call": { "call_sid": "...", "call_duration": 16, "outcome": "completed" },
  "analysis": {
    "summary": "...",
    "sentiment": "positive",
    "goal_outcome": "confirmed_this_saturday",
    "interest_level": "high",
    "captured_data": { "profession": "...", "email": "..." }
  },
  "contact": {
    "contact_name": "Animesh",
    "contact_phone": "+919609775259",
    "ghl_contact_id": null
  },
  "bot_config": { "agent_name": "...", "company_name": "...", "language": "en-IN" },
  "transcript": [
    { "role": "assistant", "content": "Hi..." },
    { "role": "user", "content": "Hello..." }
  ]
}
```

### Accessing webhook data (with body fallback)
```javascript
// n8n may wrap payload in .body or expose it directly — handle both
const webhookData = $('Wavelength Webhook').item.json;
const webhook = webhookData.body || webhookData;

// Then access fields
const leadName = webhook.contact?.contact_name || 'Valued Professional';
const leadPhone = webhook.contact?.contact_phone || '';
```

### Transcript normalization
```javascript
const transcript = typeof webhook.transcript === 'string'
    ? webhook.transcript
    : webhook.transcript.map(t => t.role.toUpperCase() + ': ' + t.content).join('\n');
```

---

## 4. Gemini API Integration

### URL pattern
```
https://asia-south1-aiplatform.googleapis.com/v1/projects/ai-calling-9238e/locations/asia-south1/publishers/google/models/gemini-2.5-flash:generateContent
```

### Authentication
```json
{
  "authentication": "predefinedCredentialType",
  "nodeCredentialType": "googleApi",
  "credentials": {
    "googleApi": {
      "id": "0ASefKpgydv7aIED",
      "name": "Google Service Account account"
    }
  }
}
```

### Request body — simple (user message only)
```javascript
const requestBody = {
  contents: [{ role: "user", parts: [{ text: prompt }] }],
  generationConfig: {
    temperature: 0.3,
    responseMimeType: "application/json"  // forces JSON output
  }
};
return [{ json: { requestBody } }];
```

### Request body — with system instruction
```javascript
const requestBody = {
  systemInstruction: { parts: [{ text: systemPrompt }] },
  contents: [{ role: "user", parts: [{ text: userPrompt }] }],
  generationConfig: {
    temperature: 0.7,
    maxOutputTokens: 4096,
    thinkingConfig: { thinkingBudget: 0 }  // disable thinking for speed
  }
};
```

### HTTP Request node config for Gemini
```json
{
  "method": "POST",
  "url": "<gemini URL>",
  "specifyBody": "json",
  "jsonBody": "={{ $json.requestBody }}",
  "options": {
    "response": { "response": { "responseFormat": "json" } }
  }
}
```

Note: Use `"=json"` for `specifyBody` when passing via expression, `"json"` when using `jsonBody` directly.

### Parsing Gemini response
```javascript
// In a Set node (simple parse)
{{ JSON.parse($json.candidates[0].content.parts[0].text) }}

// In a Code node (with error handling)
let messageText = '';
try {
  messageText = response.candidates[0].content.parts[0].text.trim();
} catch(e) {
  const candidate = response.candidates?.[0];
  if (candidate?.content?.parts) {
    messageText = candidate.content.parts[0].text.trim();
  }
}
```

---

## 5. Code Node Patterns

### Standard structure
```javascript
// 1. Get input data
const prev = $input.first().json;
const webhook = $('Wavelength Webhook').item.json;

// 2. Process / transform
const result = someTransformation(prev);

// 3. Return array of items
return [{ json: { field1: value1, field2: value2 } }];
```

### Helper functions (define inside the code node)
```javascript
// HTML formatter for AI-generated text
function formatContent(text) {
  if (!text) return '';
  return text
    .split('\n')
    .map(line => {
      line = line.trim();
      if (!line) return '';
      // Bold: **text**
      line = line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      // Italic: *text*
      line = line.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      // Bullets: •, -, →, *
      if (line.startsWith('•') || line.startsWith('- ') || line.startsWith('→') || line.startsWith('* ')) {
        const content = line.replace(/^[•\-→*]\s*/, '');
        return '<li style="margin-bottom:8px;">' + content + '</li>';
      }
      // Numbered items
      if (/^\d+[\.)]\\s/.test(line)) {
        return '<li style="margin-bottom:8px;">' + line.replace(/^\d+[\.)\s]*/, '') + '</li>';
      }
      // Paragraphs
      return '<p style="margin:0 0 10px 0;">' + line + '</p>';
    })
    .filter(line => line !== '')
    .join('\n')
    .replace(/(<li[^>]*>.*<\/li>\n?)+/g, match =>
      '<ul style="padding-left:20px;margin:12px 0;list-style:none;">' + match + '</ul>'
    );
}
```

### UUID generation (no crypto module needed)
```javascript
const uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
  const r = Math.random() * 16 | 0;
  return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
});
```

### Sanitizing AI output for template literals
```javascript
// Prevent backticks and ${} from breaking template strings
for (const key of Object.keys(sections)) {
  if (typeof sections[key] === 'string') {
    sections[key] = sections[key].replace(/`/g, "'").replace(/\$\{/g, "$ {");
  }
}
```

### Regex-based JSON extraction (when responseMimeType isn't available)
```javascript
function extractSection(json, key) {
  const regex = new RegExp('"' + key + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)\"');
  const match = json.match(regex);
  if (!match) return '';
  return match[1].replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
}
```

---

## 6. Binary Data & File Handling

### HTML → PDF via Gotenberg
```
Step 1: Code node — convert HTML string to binary
Step 2: HTTP Request — POST multipart to Gotenberg
Step 3: HTTP Request — upload resulting PDF binary to GCS
```

### Step 1: Prepare HTML Binary (Code node)
```javascript
const html = $input.first().json.html;
const binaryData = Buffer.from(html, 'utf-8');

return [{
  json: { uuid, lead_name, lead_phone },
  binary: {
    data: {
      data: binaryData.toString('base64'),
      mimeType: 'text/html',
      fileName: 'index.html'
    }
  }
}];
```

### Step 2: Gotenberg HTTP Request
```json
{
  "method": "POST",
  "url": "https://gotenberg.freedomwithai.com/forms/chromium/convert/html",
  "authentication": "genericCredentialType",
  "genericAuthType": "httpBasicAuth",
  "sendBody": true,
  "contentType": "multipart-form-data",
  "bodyParameters": {
    "parameters": [{
      "parameterType": "formBinaryData",
      "name": "files",
      "inputDataFieldName": "data"
    }]
  },
  "options": { "response": { "response": { "responseFormat": "file" } } }
}
```

### Step 3: GCS Upload
```json
{
  "method": "POST",
  "url": "=https://storage.googleapis.com/upload/storage/v1/b/fwai-reports/o?uploadType=media&name=roadmaps/{{ $('Build HTML Report').item.json.uuid }}.pdf",
  "authentication": "predefinedCredentialType",
  "nodeCredentialType": "googleApi",
  "sendBody": true,
  "contentType": "binaryData",
  "inputDataFieldName": "data"
}
```

Public URL pattern: `https://storage.googleapis.com/fwai-reports/roadmaps/{uuid}.pdf`

---

## 7. External API Patterns

### WATI WhatsApp — Session Message
```json
{
  "method": "POST",
  "url": "=https://live-mt-server.wati.io/328176/api/v1/sendSessionMessage/{{ $json.phone_clean }}",
  "sendQuery": true,
  "queryParameters": {
    "parameters": [{
      "name": "messageText",
      "value": "={{ $json.whatsapp_message + '\\n\\nHere is your roadmap: ' + $json.pdf_url }}"
    }]
  },
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [{
      "name": "Authorization",
      "value": "Bearer <WATI_TOKEN>"
    }]
  }
}
```

Note: Session messages only work within 24h of user's last message. Use `sendTemplateMessage` for cold outreach.

### GHL — Contact Lookup by Phone
```
GET https://services.leadconnectorhq.com/contacts/search/duplicate
  ?locationId=TOke3l5JIz3qqeafaEbt
  &number=%2B{phone_with_country_code}

Headers:
  Authorization: Bearer <GHL_API_KEY>
  Version: 2021-07-28
```

Response includes: `contact.id`, `contact.email`, `contact.firstName`, etc.

### GHL — Send Email
```
POST https://services.leadconnectorhq.com/conversations/messages

Headers:
  Authorization: Bearer <GHL_API_KEY>
  Version: 2021-07-28
  Content-Type: application/json

Body:
{
  "type": "Email",
  "contactId": "<ghl_contact_id>",
  "subject": "Your Personalized AI Career Roadmap",
  "html": "<email HTML content>",
  "emailFrom": "Freedom With AI <hello@freedomwithai.com>"
}
```

Response: `{ "threadId": "...", "messageId": "...", "msg": "Email queued successfully." }`

---

## 8. Connection Topology Patterns

### Linear chain (most common)
```
Webhook → Code → HTTP → Code → HTTP → Done
```

### Branch with dead-end
```
Webhook → Code → HTTP → Parse → If?
                                  ├── true → [continue chain]
                                  └── false → Skip (noOp)
```

### Fan-out (parallel after branch)
```
After Send WhatsApp → Send GHL Email (parallel)
                    → Log to Sheet (parallel)
```

### Connection JSON structure
```json
{
  "connections": {
    "Source Node": {
      "main": [
        [  // output 0 (true branch for If nodes)
          { "node": "Target A", "type": "main", "index": 0 }
        ],
        [  // output 1 (false branch for If nodes)
          { "node": "Target B", "type": "main", "index": 0 }
        ]
      ]
    }
  }
}
```

---

## 9. Testing with Pin Data

Pin data lets you test without live webhook calls:

```json
{
  "pinData": {
    "Wavelength Webhook": [{
      "json": {
        "headers": { "content-type": "application/json" },
        "params": {},
        "query": {},
        "body": {
          "event": "post_call",
          "contact": { "contact_name": "Test User", "contact_phone": "+919999999999" },
          "analysis": { "goal_outcome": "confirmed_this_saturday", "sentiment": "positive" },
          "transcript": [
            { "role": "assistant", "content": "Hi, is this Test?" },
            { "role": "user", "content": "Yes, speaking." }
          ]
        }
      }
    }]
  }
}
```

---

## 10. Error Handling

### Safe data access with fallbacks
```javascript
const leadName = webhook.contact?.contact_name || 'Valued Professional';
const leadPhone = webhook.contact?.contact_phone || '';
```

### Try-catch for unreliable data
```javascript
let whatsappMessage = '';
try {
  whatsappMessage = $('Code in JavaScript3').first().json.whatsapp_message || '';
} catch(e) {
  whatsappMessage = '';
}
```

### Clean intermediate responses (prevent context overflow)
```javascript
// After GCS upload, strip the large response
return [{ json: { upload_success: true, status: response.status || 200 } }];
```

---

## 11. Pre-Activation Checklist

Before activating any workflow:

- [ ] All credential IDs reference real n8n credentials
- [ ] Webhook path is unique across all workflows
- [ ] Phone numbers are cleaned (no `+` for WATI, with `%2B` for GHL)
- [ ] All `$('Node Name')` references match exact node names
- [ ] Gemini API URL uses correct project ID and region
- [ ] GCS bucket name and path are correct
- [ ] WATI/GHL API tokens are current
- [ ] Pin data is set for testing (remove before production use)
- [ ] `binaryMode: "separate"` if any file handling exists
- [ ] Error branches exist for conditional nodes (noOp at minimum)
