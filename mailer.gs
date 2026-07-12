/**
 * WSJ Daily — mailer (Google Apps Script)
 * ---------------------------------------
 * Trivial + bulletproof: reads the newest picks-*.json from the "WSJ-FT Daily"
 * Drive folder and emails a bare digest to everyone in the recipients Doc.
 * All fetching, curation, and link-resolution happen in a separate daily Claude
 * job (which runs from a normal IP and writes the picks file to Drive). This
 * script only touches Drive + Gmail, so Google can never CAPTCHA-block it.
 *
 * ONE-TIME SETUP:
 *   - Project Settings → timezone America/New_York.
 *   - Run installTrigger() once and authorize.
 */

// ---- CONFIG -----------------------------------------------------------------
var CONFIG = {
  // Raw URL of picks.json in your GitHub repo (GitHub Actions commits it daily).
  // Replace USERNAME/REPO with yours.
  PICKS_URL: 'https://raw.githubusercontent.com/USERNAME/REPO/main/picks.json',
  RECIPIENTS_DOC_ID: '1jbUFrqpKCN1TUfvJb5VCOKkNW6EkTMFa40FZsYA4YhA',
  SEND_HOUR: 9,                  // 9 AM in the project timezone (set to ET)
  SUBJECT_PREFIX: 'WSJ',
  REQUIRE_FRESH: true,           // only send if the picks file is dated today
  ALERT_ON_MISSING: true         // email recipient[0] if no fresh picks
};
// -----------------------------------------------------------------------------

/** Main entry — called by the daily trigger. */
function sendDaily() {
  var recipients = getRecipients();
  if (recipients.length === 0) { Logger.log('No recipients; nothing sent.'); return; }

  var data = getTodaysPicks();
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  if (!data || (CONFIG.REQUIRE_FRESH && data.date !== today)) {
    Logger.log('No fresh picks for ' + today + ' (found: ' + (data ? data.date : 'none') + ').');
    if (CONFIG.ALERT_ON_MISSING) {
      GmailApp.sendEmail(recipients[0], CONFIG.SUBJECT_PREFIX + ' — no digest today',
        'No picks file dated ' + today + ' was found in Drive, so no digest was sent.');
    }
    return;
  }

  var email = buildEmail(data);
  GmailApp.sendEmail(recipients[0], email.subject, email.textBody, {
    htmlBody: email.htmlBody, bcc: recipients.slice(1).join(','), name: 'WSJ Daily'
  });
  Logger.log('Sent to ' + recipients.length + ' recipient(s).');
}

/** Fetch picks.json from GitHub. Returns {date, picks} or null. */
function getTodaysPicks() {
  try {
    var resp = UrlFetchApp.fetch(CONFIG.PICKS_URL + '?t=' + Date.now(), { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) { Logger.log('picks fetch HTTP ' + resp.getResponseCode()); return null; }
    return JSON.parse(resp.getContentText());
  } catch (e) { Logger.log('picks fetch/parse failed: ' + e); return null; }
}

/** Bare digest email (matches the plain WSJ layout). */
function buildEmail(data) {
  var pretty = Utilities.formatDate(new Date(data.date + 'T12:00:00'),
    Session.getScriptTimeZone(), 'M/d/yyyy');
  var subject = CONFIG.SUBJECT_PREFIX + ' — ' + pretty;

  var rows = data.picks.map(function (p) {
    var link = p.url
      ? '<a href="' + p.url + '" style="color:#0b57d0;text-decoration:none;">' + escapeHtml(p.title) + '</a>'
      : '<span style="color:#888;">No WSJ pick today.</span>';
    var sum = (p.summary && p.url)
      ? '<div style="color:#555;font-size:14px;margin-top:2px;">' + escapeHtml(p.summary) + '</div>' : '';
    return '<p style="margin:0 0 20px 0;"><strong>' + escapeHtml(p.label) + ':</strong> ' + link + sum + '</p>';
  }).join('\n');

  var htmlBody =
    '<div style="font-family:Arial,Helvetica,sans-serif;font-size:16px;color:#111;line-height:1.4;">' +
      rows + '</div>';

  var textBody = data.picks.map(function (p) {
    var line = p.label + ': ' + (p.url ? p.title + ' — ' + p.url : 'No WSJ pick today.');
    if (p.summary && p.url) line += '\n' + p.summary;
    return line;
  }).join('\n\n');

  return { subject: subject, htmlBody: htmlBody, textBody: textBody };
}

// ---- helpers ----------------------------------------------------------------

function getRecipients() {
  var text = DocumentApp.openById(CONFIG.RECIPIENTS_DOC_ID).getBody().getText();
  var re = /[^\s@]+@[^\s@]+\.[^\s@]+/;
  return text.split(/\r?\n/).map(function (l) { return l.trim(); })
    .filter(function (l) { return re.test(l); }).map(function (l) { return l.match(re)[0]; });
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---- one-time / utility -----------------------------------------------------

/** Install the daily 9 AM trigger. Run once, authorize when prompted. */
function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'sendDaily') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('sendDaily').timeBased().everyDays(1)
    .atHour(CONFIG.SEND_HOUR).nearMinute(0).create();
  Logger.log('Daily trigger installed for ~' + CONFIG.SEND_HOUR + ':00 (project timezone).');
}

/** Send right now to yourself, ignoring the freshness check — for testing. */
function sendTestNow() {
  var data = getTodaysPicks();
  if (!data) { Logger.log('No picks file found in Drive.'); return; }
  var email = buildEmail(data);
  var me = getRecipients()[0] || Session.getActiveUser().getEmail();
  GmailApp.sendEmail(me, '[TEST] ' + email.subject, email.textBody,
    { htmlBody: email.htmlBody, name: 'WSJ Daily' });
  Logger.log('Test sent to ' + me + ' (picks dated ' + data.date + ')');
}
