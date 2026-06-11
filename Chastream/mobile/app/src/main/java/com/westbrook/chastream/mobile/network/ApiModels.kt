package com.westbrook.chastream.mobile.network

data class RemoteRecord(
    val id: String,
    val kind: String,
    val title: String = "",
    val summary: String = "",
    val content: String = "",
    val raw_transcript: String = "",
    val status: String,
    val style: String = "",
    val source: String = "",
    val error: String? = null,
)

data class CreateRecordResponse(
    val record: RemoteRecord,
    val job: RemoteJob,
)

data class RemoteJob(
    val id: String,
    val record_id: String,
    val status: String,
    val error: String? = null,
)

data class RecordListResponse(val items: List<RemoteRecord>)

data class VoiceprintElement(
    val id: String,
    val name: String,
    val hidden: Boolean = false,
)

data class VoiceprintCollection(
    val id: String,
    val name: String,
    val elements: List<VoiceprintElement> = emptyList(),
)

data class VoiceprintListResponse(val items: List<VoiceprintCollection>)

data class NamePayload(val name: String)

data class ElementPayload(
    val name: String? = null,
    val hidden: Boolean? = null,
)
