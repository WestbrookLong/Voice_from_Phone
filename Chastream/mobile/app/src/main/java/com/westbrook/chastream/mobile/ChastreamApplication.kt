package com.westbrook.chastream.mobile

import android.app.Application
import com.westbrook.chastream.mobile.data.AppDatabase
import com.westbrook.chastream.mobile.data.RecordRepository

class ChastreamApplication : Application() {
    val database by lazy { AppDatabase.create(this) }
    val repository by lazy { RecordRepository(this, database.recordDao()) }
}
