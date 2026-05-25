package com.westbrook.flowmobile.ime

import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class FlowAccessibilityService : AccessibilityService() {
    override fun onServiceConnected() {
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (instance === this) {
            instance = null
        }
        super.onDestroy()
    }

    fun tryClickSend(): Boolean {
        val root = rootInActiveWindow ?: return false
        val candidates =
            root.findAccessibilityNodeInfosByText("发送") +
                root.findAccessibilityNodeInfosByText("Send")

        return candidates.firstOrNull { clickNodeOrParent(it) } != null
    }

    private fun clickNodeOrParent(node: AccessibilityNodeInfo?): Boolean {
        var current = node
        while (current != null) {
            if (current.isClickable && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return true
            }
            current = current.parent
        }
        return false
    }

    companion object {
        @Volatile
        private var instance: FlowAccessibilityService? = null

        fun requestSend(): Boolean = instance?.tryClickSend() == true

        fun isEnabled(context: Context): Boolean {
            val enabledServices =
                Settings.Secure.getString(
                    context.contentResolver,
                    Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
                ) ?: return false
            val expected = ComponentName(context, FlowAccessibilityService::class.java).flattenToString()
            return enabledServices.contains(expected)
        }
    }
}
