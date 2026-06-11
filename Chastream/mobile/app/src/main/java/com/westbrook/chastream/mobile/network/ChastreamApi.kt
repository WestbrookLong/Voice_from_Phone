package com.westbrook.chastream.mobile.network

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.GET
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

interface ChastreamApi {
    @Multipart
    @POST("api/v1/quick-notes")
    suspend fun createQuickNote(
        @Part audio: MultipartBody.Part,
        @Part("style") style: RequestBody,
        @Part("source") source: RequestBody,
    ): CreateRecordResponse

    @Multipart
    @POST("api/v1/conversations")
    suspend fun createConversation(
        @Part audio: MultipartBody.Part,
        @Part("title") title: RequestBody,
        @Part("style") style: RequestBody,
        @Part("source") source: RequestBody,
        @Part("metadata_json") metadataJson: RequestBody,
    ): CreateRecordResponse

    @GET("api/v1/quick-notes")
    suspend fun quickNotes(@Query("limit") limit: Int = 30): RecordListResponse

    @GET("api/v1/quick-notes/{id}")
    suspend fun quickNote(@Path("id") id: String): RemoteRecord

    @GET("api/v1/conversations")
    suspend fun conversations(@Query("limit") limit: Int = 30): RecordListResponse

    @GET("api/v1/conversations/{id}")
    suspend fun conversation(@Path("id") id: String): RemoteRecord

    @GET("api/v1/voiceprints")
    suspend fun voiceprints(): VoiceprintListResponse

    @POST("api/v1/voiceprints/collections")
    suspend fun createVoiceprintCollection(@Body payload: NamePayload): VoiceprintCollection

    @DELETE("api/v1/voiceprints/collections/{collectionId}")
    suspend fun deleteVoiceprintCollection(@Path("collectionId") collectionId: String)

    @Multipart
    @POST("api/v1/voiceprints/collections/{collectionId}/elements")
    suspend fun createVoiceprintElement(
        @Path("collectionId") collectionId: String,
        @Part("name") name: RequestBody,
        @Part samples: List<MultipartBody.Part>,
    ): VoiceprintElement

    @PATCH("api/v1/voiceprints/collections/{collectionId}/elements/{elementId}")
    suspend fun updateVoiceprintElement(
        @Path("collectionId") collectionId: String,
        @Path("elementId") elementId: String,
        @Body payload: ElementPayload,
    ): VoiceprintElement

    @DELETE("api/v1/voiceprints/collections/{collectionId}/elements/{elementId}")
    suspend fun deleteVoiceprintElement(
        @Path("collectionId") collectionId: String,
        @Path("elementId") elementId: String,
    )
}
