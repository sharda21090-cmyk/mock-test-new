const ui = SpreadsheetApp.getUi();

function onOpen() {

  ui.createMenu('TB Tool')
    .addItem('Update', 'all')
    .addItem('Task Rejected', 'taskrejected')
    .addItem('File Update', 'fetchfilefromdrive')
    .addItem('Completion Mail', 'taskcompletionmail_2')
    .addItem('Publish to Vercel', 'triggerPublish')
    .addToUi();
}

 function all() {
  taskidautogen4();
  taskstatus();

 }
function taskidautogen4() {

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Main sheet");

  // Get all values in columns B and C
  var rangeValues = sheet.getRange("B2:C" + sheet.getLastRow()).getValues();

  // Find the maximum Task ID number
  var taskNumbers = rangeValues.map(function(row) {
    var match = row[0].match(/D-(\d+)/);
    return match ? parseInt(match[1]) : 0;
  });

  var maxTaskNumber = Math.max(...taskNumbers);

  // Iterate through each row and generate Task ID for empty rows in column B where column C is not empty
  for (var i = 0; i < rangeValues.length; i++) {
    if (rangeValues[i][0] === "" && rangeValues[i][1] !== "") {
      // Increment the maximum Task ID by 1
      maxTaskNumber += 1;

      // Create the new Task ID
      var newTaskId = "D-" + maxTaskNumber;

      // Set the new Task ID in the current empty row of column B
      sheet.getRange(i + 2, 2).setValue(newTaskId); // Adding 2 to convert from 0-based index to 1-based index
    }
  }
}
  
function taskrejected() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet1 = ss.getSheetByName("Main sheet");
  var lastRow1 = sheet1.getLastRow();

  for (var i = 2; i <= lastRow1; i++) {
    var taskID = sheet1.getRange('B' + i).getValue();
    var createdBy = sheet1.getRange('F' + i).getValue();
    var tasktitle = sheet1.getRange('J' + i).getValue();
    var facultiesName = sheet1.getRange('H' + i).getValue();
    var sentStatus = sheet1.getRange('AP' + i).getValue();
    var recipient = sheet1.getRange('G' + i).getValue();
    var recipient1 = sheet1.getRange('I' + i).getValue();
    var recipient2 = sheet1.getRange('AA' + i).getValue();
    var rejectionreason = sheet1.getRange('AQ' + i).getValue();
    var status = sheet1.getRange('A' + i).getValue();
    var currentDateTime = new Date();
    var ccRecipients = ['manoj.verma@testbook.com', 'daman.dtp@testbook.com', 'prince.singh@testbook.com','surbhi.jain@testbook.com','gourav.kumar.singh@testbook.com','deepak.sarwan.kumar@testbook.com'];
    var subject = "Task ID: " + taskID + " || Rejected || Task Title: " + tasktitle + "_ " + facultiesName;
    var finalMsg = `
      <p>Hello ${createdBy} and ${facultiesName},</p>
      <p>Your Task <b>${taskID}</b> is Rejected. ,</p>
      ,</p>Reason: ${rejectionreason}.</p>
    `;

    if (rejectionreason !== "" && status == "Rejected" && sentStatus == "") {
      var message = {
        to: recipient,
        cc: ccRecipients.join(', ') + ', ' + recipient1 + ', ' + recipient2,
        subject: subject,
        htmlBody: finalMsg
      };
      MailApp.sendEmail(message);
      sheet1.getRange("BC" + i).setValue(currentDateTime);
      sheet1.getRange("AP" + i).setValue("Task REJECTED");
    }
  }
}

function fetchfilefromdrive() {
  // Sheet and Drive folder details
  const sheetName = "Main sheet";
  const taskIDColumn = "B";
  const titleColumn = "J";
  const checkColumn = "AX"; // Column to check if not empty
  const pdfOutputColumn = "AZ";
  const pptOutputColumn = "AY";
  const folderId = "1ZdWJeoCF8sKx3LyWueav4Fjr8-mo_1SQ";

  try {
    // Access the sheet and folder
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) throw new Error(`Sheet "${sheetName}" not found.`);
    const folder = DriveApp.getFolderById(folderId);
    if (!folder) throw new Error(`Folder with ID "${folderId}" not found.`);

    // Get the data from the sheet
    const taskIDs = sheet.getRange(taskIDColumn + "2:" + taskIDColumn + sheet.getLastRow()).getValues();
    const titles = sheet.getRange(titleColumn + "2:" + titleColumn + sheet.getLastRow()).getValues();
    const checkValues = sheet.getRange(checkColumn + "2:" + checkColumn + sheet.getLastRow()).getValues();
    const pdfLinks = sheet.getRange(pdfOutputColumn + "2:" + pdfOutputColumn + sheet.getLastRow()).getValues();
    const pptLinks = sheet.getRange(pptOutputColumn + "2:" + pptOutputColumn + sheet.getLastRow()).getValues();

    // Loop through the rows
    for (let i = 0; i < taskIDs.length; i++) {
      const taskId = taskIDs[i][0];
      const title = titles[i][0];
      const checkValue = checkValues[i][0];
      const existingPdfLink = pdfLinks[i][0];
      const existingPptLink = pptLinks[i][0];

      if (checkValue && taskId && title) {
        console.log(`Processing Task ID: ${taskId}, Title: ${title}`);

        const newFileName = `${taskId}_${title}`;

        // Check for PDF file only if the output cell is empty
        if (!existingPdfLink) {
          const pdfFiles = folder.getFilesByName(`${taskId}.pdf`);
          if (pdfFiles.hasNext()) {
            const pdfFile = pdfFiles.next();
            pdfFile.setName(newFileName + ".pdf"); // Rename the file
            const pdfFileUrl = pdfFile.getUrl();
            sheet.getRange(pdfOutputColumn + (i + 2)).setValue(pdfFileUrl);
          } else {
            console.log(`PDF file not found for Task ID: ${taskId}`);
          }
        }

        // Check for PPTX file only if the output cell is empty
        if (!existingPptLink) {
          const pptxFiles = folder.getFilesByName(`${taskId}.pptx`);
          if (pptxFiles.hasNext()) {
            const pptxFile = pptxFiles.next();
            pptxFile.setName(newFileName + ".pptx"); // Rename the file
            const pptxFileUrl = pptxFile.getUrl();
            sheet.getRange(pptOutputColumn + (i + 2)).setValue(pptxFileUrl);
          } else {
            console.log(`PPTX file not found for Task ID: ${taskId}`);
          }
        }
      } else {
        console.log(`Skipping row ${i + 2}: Missing data or column AM is empty.`);
      }
    }
  } catch (error) {
    console.error(`Error: ${error.message}`);
  }
}

function getNameFromEmail(email) {
  if (!email) return "Faculty";
  const namePart = email.split("@")[0];
  return namePart
    .replace(/[._]/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
}

function taskcompletionmail_2() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet1 = ss.getSheetByName("Main sheet");
  const lastRow1 = sheet1.getLastRow();

  const headers = sheet1.getRange(1, 1, 1, sheet1.getLastColumn()).getValues()[0];

  const getColumnIndex = (header) => headers.indexOf(header) + 1;

  const taskIDCol = getColumnIndex('Task Id');
  const createdByCol = getColumnIndex('Created By');
  const taskTitleCol = getColumnIndex('Task Name');
  const pptCol = getColumnIndex('PPT');
  const genpdfCol = getColumnIndex('GenPdf');
  const facultiesNameCol = getColumnIndex('Faculties Name');
  const sentStatusCol = getColumnIndex('Mail Sent TimeStamp');
  const recipientCol = getColumnIndex('Email Address');
  const recipient1Col = getColumnIndex('Faculties Mail');
  const recipient2Col = getColumnIndex('Category Manager Mail');
  const mockTestCol = getColumnIndex('HTML Link'); // Added HTML Link column
  const approvalCheckboxCol = getColumnIndex('Check & Approve');

  const ccRecipients = [
    'daman.dtp@testbook.com',
    'narender.choudhary@testbook.com',
    'surbhi.jain@testbook.com'
  ];

  for (let i = 2; i <= lastRow1; i++) {
    try {
      const approvalCheckbox = sheet1.getRange(i, approvalCheckboxCol).getValue();
      if (approvalCheckbox !== true) continue;

      const taskID = sheet1.getRange(i, taskIDCol).getValue();
      const createdBy = sheet1.getRange(i, createdByCol).getValue();
      const taskTitle = sheet1.getRange(i, taskTitleCol).getValue();
      const pptLink = sheet1.getRange(i, pptCol).getValue();
      const pdfLink = sheet1.getRange(i, genpdfCol).getValue();
      const mockTestLink = sheet1.getRange(i, mockTestCol).getValue(); // Pulls link from Sheet directly
      const facultiesName = sheet1.getRange(i, facultiesNameCol).getValue();
      const sentStatus = sheet1.getRange(i, sentStatusCol).getValue();

      const to = sheet1.getRange(i, recipient1Col).getValue();
      const facultiesName_gen = getNameFromEmail(to);
      const cc = [...ccRecipients,
        sheet1.getRange(i, recipientCol).getValue(),
        sheet1.getRange(i, recipient2Col).getValue(),

      ].filter(Boolean).join(',');

      if (!pptLink || sentStatus) continue;

      // ✅ Inbox-friendly subject
      const subject = `Task ID: ${taskID} || Completed || Task Title: ${taskTitle} || ${facultiesName_gen}`;

      // ✅ Clean & human-like HTML body
      let htmlBody = `
        <p>Dear ${facultiesName_gen},</p>
      `;

      if (pdfLink) {
        // ✅ PPT + PDF present
        htmlBody += `
          <p>The <b>Class PPT and Reference PDF</b> for your upcoming live class are ready. Please find the links below:</p>

          <p>
            <b>Class PPT:</b>  <a href="${pptLink}">${taskTitle}</a><br>
            <br>
            <b>Reference PDF:</b>  <a href="${pdfLink}">${taskTitle}</a><br>
        `;
        
        if (mockTestLink) {
            htmlBody += `<br><b>Mock Test Link:</b> <a href="${mockTestLink}">Click here to attempt</a>`;
        }
        
        htmlBody += `
          </p>
          <br>
        `;
      } else {
        // ✅ Only PPT present
        htmlBody += `
          <p>The <b>Class PPT</b> for your upcoming live class is ready. Please find the link below:</p>

          <p>
            <b>Class PPT:</b> <a href="${pptLink}">${taskTitle}</a><br>
        `;
        
        if (mockTestLink) {
            htmlBody += `<br><b>Mock Test Link:</b> <a href="${mockTestLink}">Click here to attempt</a>`;
        }
3
        htmlBody += `
          </p>
          <br>
        `;
      }

      htmlBody += `
        <p>Kindly acknowledge once received.</p>

        <p>
          Regards,<br>
          <b>DTP Team</b>
        </p>

        <br><br>

        <p style="font-size:12px;color:#7d7c7c;">
          Note: If you find this email in your Spam folder, kindly mark it as <b>Not Spam</b> so that you receive future class materials directly in your Inbox.
        </p>
      `;

      // 🔐 SHARE FILE ACCESS (ADD THIS BLOCK)
      const facultyEmail = to;

      const pptFileId = getFileIdFromUrl(pptLink);
      if (pptFileId && facultyEmail) {
        DriveApp.getFileById(pptFileId).addEditor(facultyEmail);
      }

      const pdfFileId = getFileIdFromUrl(pdfLink);
      if (pdfFileId && facultyEmail) {
        DriveApp.getFileById(pdfFileId).addEditor(facultyEmail);
      }
      
      // ✅ Use GmailApp (VERY IMPORTANT)
      GmailApp.sendEmail(
        to,
        subject,
        "Live class materials shared.",
        {
          htmlBody: htmlBody,
          cc: cc,
          name: "DTP Team",
          replyTo: "narender.choudhary@testbook.com"
        }
      );

      // ✅ Log timestamp
      sheet1.getRange(i, sentStatusCol)
        .setValue(Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss"));

      // ✅ Anti-spam delay
      Utilities.sleep(1500);

    } catch (err) {
      console.error(`Row ${i} failed: ${err.message}`);
    }
  }
}

function getFileIdFromUrl(url) {
  if (!url) return null;
  const match = url.match(/[-\w]{25,}/);
  return match ? match[0] : null;
}


function taskstatus() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Main sheet");
  
  // Get all values from columns A to BD
  var range = sheet.getRange("A2:BD" + sheet.getLastRow());
  var values = range.getValues(); // Get all rows as a 2D array
  
  var statuses = []; // To store status for each row
  
  // Loop through each row and calculate status
  for (var i = 0; i < values.length; i++) {
    var row = values[i]; // Get the current row
    var status;

    // Determine the status based on the row values
    if (row[0] === "Deleted" || row[0] === "Hold" || row[0] === "Withdrawn" || row[0] === "Rejected") {
      status = row[0]; // Keep the status unchanged
    } else if (row[54] != "") {
      status = "Completed";
    } else if (row[49] != "") {
      status = "Check and Approve";
    } else if (row[48] != "") {
      status = "Creation";
    } else if (row[3] != "") {
      status = "Assigning Step";
    } else {
      status = "";
    }

    statuses.push([status]); // Add status to the list
  }
  
  // Update column A with the calculated statuses
  sheet.getRange(2, 1, statuses.length, 1).setValues(statuses);
}


function removeDuplicateRows() {
  const sheetName = "Archived"; // Change to your sheet name
  const rangeToCheck = "A:BC"; // Change to the range you want to check
  
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  if (!sheet) {
    Logger.log(`Sheet "${sheetName}" not found.`);
    return;
  }
  
  const data = sheet.getRange(rangeToCheck).getValues();
  const uniqueData = [];
  const seen = new Map();

  uniqueData.push(data[0]); // Keep the header row

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const key = row[1]; // Column B (index 1)
    const hasDataInAYAZ = row[50] !== "" || row[51] !== ""; // AY (index 50) or AZ (index 51)

    if (seen.has(key)) {
      const existingRow = seen.get(key);
      const existingHasDataInAYAZ = existingRow[50] !== "" || existingRow[51] !== "";

      if (!existingHasDataInAYAZ && hasDataInAYAZ) {
        // Replace the empty AY/AZ row with the row that has data
        seen.set(key, row);
      }
    } else {
      seen.set(key, row);
    }
  }

  // Convert map values to an array and write back to the sheet
  uniqueData.push(...Array.from(seen.values()));

  sheet.clearContents();
  sheet.getRange(1, 1, uniqueData.length, uniqueData[0].length).setValues(uniqueData);

  Logger.log("Duplicates removed based on column B while considering AY and AZ.");
}

/**
 * Triggers the GitHub Actions workflow "Sync LMS Questions"
 * Uses GitHub API (repository_dispatch or workflow_dispatch)
 */
function triggerPublish() {
  const GITHUB_OWNER = 'sharda21090-cmyk';
  const GITHUB_REPO = 'mock-test-new';
  const WORKFLOW_ID = 'sync-lms.yml';
  const REF = 'main';

  const scriptProperties = PropertiesService.getScriptProperties();
  const githubToken = scriptProperties.getProperty('GITHUB_PAT');
  const lmsEmail = scriptProperties.getProperty('LMS_EMAIL') || 'manjot.surjit.singh@testbook.com';
  const lmsPassword = scriptProperties.getProperty('LMS_PASSWORD') || 'Manjot_123';

  if (!githubToken) {
    ui.alert('Error', 'GitHub Token (GITHUB_PAT) not found in Script Properties. Please check your Project Settings.', ui.ButtonSet.OK);
    return;
  }

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_ID}/dispatches`;
  
  const payload = {
    "ref": REF,
    "inputs": {
      "LMS_EMAIL": lmsEmail,
      "LMS_PASSWORD": lmsPassword
    }
  };

  const options = {
    "method": "post",
    "contentType": "application/json",
    "headers": {
      "Authorization": "Bearer " + githubToken,
      "Accept": "application/vnd.github.v3+json"
    },
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    if (code === 204) {
      ui.alert('Success', 'Publishing triggered successfully! Your changes will be live on Vercel in ~1 minute.', ui.ButtonSet.OK);
    } else {
      ui.alert('Publish Failed', 'GitHub error ' + code + ': ' + response.getContentText(), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert('Technical Error', 'Failed to connect to GitHub: ' + e.toString(), ui.ButtonSet.OK);
  }
}

/**
 * Utility to reset stored credentials if needed
 */
function resetStoredCredentials() {
  PropertiesService.getScriptProperties().deleteAllProperties();
  ui.alert('Credentials Cleared', 'All stored GitHub and LMS credentials have been removed.', ui.ButtonSet.OK);
}
