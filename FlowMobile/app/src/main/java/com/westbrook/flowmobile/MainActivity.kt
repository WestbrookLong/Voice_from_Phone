package com.westbrook.flowmobile

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.Settings
import android.view.inputmethod.InputMethodManager
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.westbrook.flowmobile.databinding.ActivityMainBinding
import com.westbrook.flowmobile.ime.FlowAccessibilityService

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

    private val audioPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {
            renderStatus()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding =
            runCatching { ActivityMainBinding.inflate(layoutInflater) }
                .getOrElse {
                    finish()
                    return
                }
        setContentView(binding.root)

        binding.enableKeyboardButton.setOnClickListener {
            startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        }

        binding.switchKeyboardButton.setOnClickListener {
            val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            imm.showInputMethodPicker()
        }

        binding.enableAccessibilityButton.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }

        binding.allowMicButton.setOnClickListener {
            audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        runCatching { renderStatus() }
    }

    override fun onResume() {
        super.onResume()
        runCatching { renderStatus() }
    }

    private fun renderStatus() {
        val hasMicPermission =
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED

        binding.micPermissionValue.text =
            if (hasMicPermission) getString(R.string.status_ready) else getString(R.string.status_missing)
        binding.keyboardHintValue.text = if (isImeEnabled()) getString(R.string.status_ready) else getString(R.string.status_pending)
        binding.accessibilityValue.text =
            if (FlowAccessibilityService.isEnabled(this)) getString(R.string.status_ready) else getString(R.string.status_optional)
    }

    private fun isImeEnabled(): Boolean {
        val enabled =
            Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_INPUT_METHODS)
                ?: return false
        return enabled.contains(packageName)
    }
}
