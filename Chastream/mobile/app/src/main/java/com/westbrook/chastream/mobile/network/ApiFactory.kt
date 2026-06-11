package com.westbrook.chastream.mobile.network

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object ApiFactory {
    fun create(context: Context): ChastreamApi {
        val preferences = context.getSharedPreferences("server", Context.MODE_PRIVATE)
        val baseUrl = preferences.getString(
            "baseUrl",
            "http://106.53.94.254/chastream/",
        )!!.let { if (it.endsWith("/")) it else "$it/" }
        val token = preferences.getString("apiToken", "").orEmpty()
        val client = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.MINUTES)
            .writeTimeout(5, TimeUnit.MINUTES)
            .addInterceptor { chain ->
                val request = chain.request().newBuilder().apply {
                    if (token.isNotBlank()) header("Authorization", "Bearer $token")
                }.build()
                chain.proceed(request)
            }
            .addInterceptor(
                HttpLoggingInterceptor().apply {
                    level = HttpLoggingInterceptor.Level.BASIC
                },
            )
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ChastreamApi::class.java)
    }
}
