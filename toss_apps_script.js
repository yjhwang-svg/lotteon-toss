/**
 * 토스update → 토스업로드 자동 업데이트 Google Apps Script
 *
 * 설치 방법:
 * 1. 해당 구글 시트 > 확장 프로그램 > Apps Script
 * 2. 이 코드를 붙여넣고 저장
 * 3. setupDailyTrigger() 함수를 한 번 실행 (매일 오전 10시 트리거 등록)
 * 4. 배포 > 새 배포 > 웹 앱 > 액세스: 모든 사용자 > 배포
 *    → 생성된 URL을 WEB_APP_URL에 붙여넣고 다시 저장 & 배포
 */

// ── 설정 ──────────────────────────────────────────
var SOURCE_SHEET = "토스update";
var TARGET_SHEET = "토스업로드";
var SLACK_WEBHOOK_URL = "https://hooks.slack.com/triggers/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";
var SLACK_EMAIL = "x-aaaatxo5yffjiqwaynov33b5re@madupteam.slack.com";  // 폴백용
var WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyxut38QZblUBpsYu_v4KxUGXj8d4-dLZ2GJihvu5qfv_VDhin1m6INSjme1Bu0d31A/exec";

// ── 유틸 ──────────────────────────────────────────
function formatDate(date) {
  var y = date.getFullYear();
  var m = ("0" + (date.getMonth() + 1)).slice(-2);
  var d = ("0" + date.getDate()).slice(-2);
  return y + "-" + m + "-" + d;
}

function parseDate(dateStr) {
  var parts = dateStr.split("-");
  return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
}

function findDateColumn(headerRow, targetDate) {
  for (var i = 0; i < headerRow.length; i++) {
    var cell = headerRow[i];
    if (cell instanceof Date) cell = formatDate(cell);
    if (String(cell).trim() === targetDate) return i;
  }
  return -1;
}

// ── 채널상세 누락 행 탐지 ─────────────────────────
function findMissingChannelRows(srcData, colIdx) {
  var missing = [];
  for (var i = 1; i < srcData.length; i++) {
    var channel = String(srcData[i][0] || "").trim();
    var value = srcData[i][colIdx];
    var hasValue = (value !== "" && value !== null && value !== undefined);
    if (hasValue && !channel) {
      missing.push(i + 1);
    }
  }
  return missing;
}

// ── 중복 방지 & 재실행용 삭제 ─────────────────────
function isAlreadyUploaded(tgtSheet, targetDate) {
  var data = tgtSheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    var cellVal = data[i][0];
    if (cellVal instanceof Date) cellVal = formatDate(cellVal);
    if (String(cellVal).trim() === targetDate) return true;
  }
  return false;
}

function deleteRowsForDate(tgtSheet, targetDate) {
  var data = tgtSheet.getDataRange().getValues();
  var rowsToDelete = [];
  for (var i = 1; i < data.length; i++) {
    var cellVal = data[i][0];
    if (cellVal instanceof Date) cellVal = formatDate(cellVal);
    if (String(cellVal).trim() === targetDate) rowsToDelete.push(i + 1);
  }
  for (var j = rowsToDelete.length - 1; j >= 0; j--) {
    tgtSheet.deleteRow(rowsToDelete[j]);
  }
  return rowsToDelete.length;
}

// ── 메인 업로드 로직 ──────────────────────────────
function updateForDate(targetDate, force) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var srcSheet = ss.getSheetByName(SOURCE_SHEET);
  var tgtSheet = ss.getSheetByName(TARGET_SHEET);

  if (!srcSheet || !tgtSheet) {
    return { ok: false, msg: "시트를 찾을 수 없습니다." };
  }

  var srcData = srcSheet.getDataRange().getValues();
  var header = srcData[0];
  var colIdx = findDateColumn(header, targetDate);

  if (colIdx === -1) {
    return { ok: false, msg: "토스update에서 '" + targetDate + "' 열을 찾을 수 없습니다." };
  }

  var missingRows = findMissingChannelRows(srcData, colIdx);

  if (isAlreadyUploaded(tgtSheet, targetDate)) {
    if (force) {
      deleteRowsForDate(tgtSheet, targetDate);
    } else {
      return { ok: true, msg: targetDate + " 데이터가 이미 존재합니다.", missingRows: missingRows, skipped: true };
    }
  }

  var rows = [];
  rows.push([targetDate, "토스", "-", "없음", "없음", 0, 0, 0]);

  for (var i = 1; i < srcData.length; i++) {
    var channel = String(srcData[i][0] || "").trim();
    if (!channel) continue;
    var value = srcData[i][colIdx];
    if (value === "" || value === null || value === undefined) continue;
    rows.push([targetDate, "토스", "-", "없음", channel, 0, value, 100000]);
  }

  var startRow = tgtSheet.getLastRow() + 1;
  var range = tgtSheet.getRange(startRow, 1, rows.length, 8);
  range.setValues(rows);
  range.setFontFamily("Arial");
  range.setFontSize(8);

  var msg = targetDate + " 업로드 완료: " + rows.length + "행 (디폴트 1 + 소재 " + (rows.length - 1) + ")";
  return { ok: true, msg: msg, missingRows: missingRows, count: rows.length };
}

// ── 구간 업로드 ───────────────────────────────────
function updateForRange(startDate, endDate, force) {
  var results = [];
  var current = parseDate(startDate);
  var end = parseDate(endDate);

  while (current <= end) {
    var dateStr = formatDate(current);
    var result = updateForDate(dateStr, force);
    results.push({ date: dateStr, result: result });
    current.setDate(current.getDate() + 1);
  }
  return results;
}

// ── 슬랙 알림 ─────────────────────────────────────
function sendSlackAlert(result, targetDate) {
  if (SLACK_WEBHOOK_URL) {
    sendSlackWebhook(result, targetDate);
  } else {
    sendSlackEmail(result, targetDate);
  }
}

function sendSlackWebhook(result, targetDate) {
  var icon = result.skipped ? "ℹ️" : (result.ok ? "✅" : "❌");
  var text = icon + " [토스봇] " + targetDate + "\n" + result.msg;

  if (result.missingRows && result.missingRows.length > 0) {
    text += "\n\n⚠️ 채널상세 업데이트 필요:";
    for (var i = 0; i < result.missingRows.length; i++) {
      text += "\n   • " + result.missingRows[i] + "행";
    }
  }

  var payload = { text: text };
  UrlFetchApp.fetch(SLACK_WEBHOOK_URL, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload)
  });
}

function sendSlackEmail(result, targetDate) {
  var subject = "[토스봇] " + targetDate;
  var body = "";

  if (result.skipped) {
    body += "ℹ️ " + result.msg + "\n";
  } else if (result.ok) {
    body += "✅ " + result.msg + "\n";
  } else {
    body += "❌ " + result.msg + "\n";
  }

  if (result.missingRows && result.missingRows.length > 0) {
    body += "\n⚠️ 채널상세 업데이트 필요:\n";
    for (var i = 0; i < result.missingRows.length; i++) {
      body += "  • " + result.missingRows[i] + "행 채널상세 업데이트 필요\n";
    }
  }

  if (WEB_APP_URL) {
    body += "\n링크: " + WEB_APP_URL;
  }

  MailApp.sendEmail({ to: SLACK_EMAIL, subject: subject, body: body });
}

function sendSlackAlertBatch(results) {
  var successDates = [];
  var failDates = [];
  var allMissing = [];

  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    if (r.result.ok && !r.result.skipped) successDates.push(r.date);
    else if (r.result.skipped) {} // 건너뜀
    else failDates.push(r.date + ": " + r.result.msg);

    if (r.result.missingRows) {
      for (var j = 0; j < r.result.missingRows.length; j++) {
        allMissing.push(r.date + " " + r.result.missingRows[j] + "행");
      }
    }
  }

  var combined = {
    ok: failDates.length === 0,
    msg: "",
    missingRows: null
  };

  if (successDates.length > 0) {
    combined.msg += "업로드 완료: " + successDates.join(", ");
  }
  if (failDates.length > 0) {
    combined.msg += (combined.msg ? "\n" : "") + "실패: " + failDates.join(", ");
  }
  if (combined.msg === "") {
    combined.msg = "변경사항 없음 (이미 업로드된 날짜)";
    combined.skipped = true;
  }

  if (allMissing.length > 0) {
    combined.missingRows = allMissing;
  }

  var targetLabel = results.length === 1
    ? results[0].date
    : results[0].date + " ~ " + results[results.length - 1].date;

  if (SLACK_WEBHOOK_URL) {
    sendSlackWebhookBatch(combined, targetLabel);
  } else {
    sendSlackEmailBatch(combined, targetLabel);
  }
}

function sendSlackWebhookBatch(result, targetLabel) {
  var icon = result.skipped ? "ℹ️" : (result.ok ? "✅" : "❌");
  var text = icon + " [토스봇] " + targetLabel + "\n" + result.msg;

  if (result.missingRows && result.missingRows.length > 0) {
    text += "\n\n⚠️ 채널상세 업데이트 필요:";
    for (var i = 0; i < result.missingRows.length; i++) {
      text += "\n   • " + result.missingRows[i];
    }
  }

  UrlFetchApp.fetch(SLACK_WEBHOOK_URL, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ text: text })
  });
}

function sendSlackEmailBatch(result, targetLabel) {
  var subject = "[토스봇] " + targetLabel;
  var body = (result.ok ? "✅ " : "❌ ") + result.msg + "\n";

  if (result.missingRows && result.missingRows.length > 0) {
    body += "\n⚠️ 채널상세 업데이트 필요:\n";
    for (var i = 0; i < result.missingRows.length; i++) {
      body += "  • " + result.missingRows[i] + " 채널상세 업데이트 필요\n";
    }
  }

  if (WEB_APP_URL) {
    body += "\n링크: " + WEB_APP_URL;
  }

  MailApp.sendEmail({ to: SLACK_EMAIL, subject: subject, body: body });
}

// ── 매일 자동 실행 (트리거용) ─────────────────────
function runTossUpdate() {
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var targetDate = formatDate(yesterday);

  var result = updateForDate(targetDate, false);
  Logger.log(result.msg);
  sendSlackAlert(result, targetDate);
}

// ── 웹앱 (재실행 UI) ──────────────────────────────
function doGet(e) {
  var dateParam = (e && e.parameter && e.parameter.date) || "";
  var endParam = (e && e.parameter && e.parameter.end) || "";
  var run = (e && e.parameter && e.parameter.run) || "";

  if (run === "1" && dateParam) {
    var results;
    if (endParam && endParam !== dateParam) {
      results = updateForRange(dateParam, endParam, true);
    } else {
      var r = updateForDate(dateParam, true);
      results = [{ date: dateParam, result: r }];
    }

    sendSlackAlertBatch(results);

    var label = endParam && endParam !== dateParam
      ? dateParam + " ~ " + endParam
      : dateParam;

    var bodyHtml = "";
    for (var i = 0; i < results.length; i++) {
      var r = results[i];
      var icon = r.result.ok ? "✅" : "❌";
      bodyHtml += "<div style='padding:4px 0'>" + icon + " " + r.date + " — " + r.result.msg + "</div>";
      if (r.result.missingRows && r.result.missingRows.length > 0) {
        bodyHtml += "<div style='color:#e65100;padding-left:20px'>⚠️ 채널상세 누락: "
          + r.result.missingRows.join("행, ") + "행</div>";
      }
    }

    var webUrl = ScriptApp.getService().getUrl();
    var resultHtml = "<!DOCTYPE html><html><head><meta charset='utf-8'>"
      + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
      + "<style>"
      + "body{font-family:Arial,sans-serif;max-width:520px;margin:40px auto;padding:20px;background:#f5f5f5;color:#333}"
      + ".card{background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 8px rgba(0,0,0,.08)}"
      + "h2{margin:0 0 16px;font-size:20px;color:#1976d2}"
      + ".back{display:inline-block;margin-top:20px;padding:10px 28px;background:#1976d2;color:#fff;"
      + "text-decoration:none;border-radius:8px;font-weight:bold}"
      + "</style></head><body><div class='card'>"
      + "<h2>🔄 " + label + " 재실행 결과</h2>"
      + bodyHtml
      + "<a class='back' href='" + webUrl + "'>← 돌아가기</a>"
      + "</div></body></html>";

    return HtmlService.createHtmlOutput(resultHtml);
  }

  // 날짜 선택 폼
  var webUrl = ScriptApp.getService().getUrl();
  var today = formatDate(new Date());
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var yestStr = formatDate(yesterday);

  var html = "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    + "<style>"
    + "body{font-family:Arial,sans-serif;max-width:520px;margin:40px auto;padding:20px;background:#f5f5f5;color:#333}"
    + ".card{background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 8px rgba(0,0,0,.08)}"
    + "h2{margin:0 0 8px;font-size:22px;color:#1976d2}"
    + ".sub{color:#888;font-size:13px;margin-bottom:24px}"
    + "label{display:block;font-weight:bold;margin:14px 0 6px;font-size:14px}"
    + "input[type=date]{font-size:16px;padding:10px 14px;border:1.5px solid #ddd;border-radius:8px;"
    + "width:100%;box-sizing:border-box}"
    + "input[type=date]:focus{border-color:#1976d2;outline:none}"
    + ".row{display:flex;gap:12px}"
    + ".row>div{flex:1}"
    + "button{width:100%;padding:13px;font-size:16px;font-weight:bold;border:none;border-radius:8px;"
    + "cursor:pointer;margin-top:20px;transition:background .2s}"
    + ".btn-primary{background:#1976d2;color:#fff}"
    + ".btn-primary:hover{background:#1565c0}"
    + ".note{font-size:12px;color:#aaa;margin-top:14px;text-align:center}"
    + "</style></head><body><div class='card'>"
    + "<h2>🔄 토스봇 재실행</h2>"
    + "<p class='sub'>날짜를 선택하고 재실행하세요. 기존 데이터는 삭제 후 다시 업로드됩니다.</p>"
    + "<form action='" + webUrl + "' method='get'>"
    + "<div class='row'>"
    + "<div><label>시작일</label><input type='date' name='date' value='" + (dateParam || yestStr) + "' required></div>"
    + "<div><label>종료일</label><input type='date' name='end' value='" + (endParam || dateParam || yestStr) + "' required></div>"
    + "</div>"
    + "<input type='hidden' name='run' value='1'>"
    + "<button type='submit' class='btn-primary'>이 기간 재실행</button>"
    + "</form>"
    + "<p class='note'>시작일 = 종료일이면 하루만 실행됩니다</p>"
    + "</div></body></html>";

  return HtmlService.createHtmlOutput(html);
}

// ── 트리거 등록 (최초 1회) ────────────────────────
function setupDailyTrigger() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "runTossUpdate") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  ScriptApp.newTrigger("runTossUpdate")
    .timeBased()
    .everyDays(1)
    .atHour(10)
    .create();

  Logger.log("매일 오전 10시 트리거가 등록되었습니다.");
}
