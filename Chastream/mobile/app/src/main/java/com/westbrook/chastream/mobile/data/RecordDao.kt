package com.westbrook.chastream.mobile.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface RecordDao {
    @Query("SELECT * FROM records ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<RecordEntity>>

    @Query("SELECT * FROM records WHERE kind = :kind ORDER BY createdAt DESC")
    fun observeKind(kind: String): Flow<List<RecordEntity>>

    @Query("SELECT * FROM records WHERE kind = 'quick_note' ORDER BY createdAt DESC LIMIT :limit")
    suspend fun recentNotes(limit: Int): List<RecordEntity>

    @Query("SELECT * FROM records WHERE id = :id LIMIT 1")
    suspend fun get(id: String): RecordEntity?

    @Query("SELECT * FROM records WHERE id = :id LIMIT 1")
    fun observe(id: String): Flow<RecordEntity?>

    @Query("SELECT * FROM records WHERE status IN ('local', 'failed') ORDER BY createdAt LIMIT 1")
    suspend fun nextPending(): RecordEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(record: RecordEntity)

    @Query("DELETE FROM records WHERE id = :id")
    suspend fun delete(id: String)

    @Query("DELETE FROM records WHERE id IN (:ids)")
    suspend fun deleteMany(ids: List<String>)
}
