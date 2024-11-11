    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        sourceName TEXT,
        timestamp INTEGER,
        message TEXT,
        groupId TEXT,
        groupName TEXT,
        attachmentPaths TEXT,
        attachmentDescriptions TEXT,
        processedAt INTEGER,
        quoteId INTEGER,
        quoteAuthor TEXT,
        quoteText TEXT
    )