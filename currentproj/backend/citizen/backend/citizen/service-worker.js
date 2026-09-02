// ============================================================
// ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
// service-worker.js — v13.0
//
// BROWSER PUSH NOTIFICATION SERVICE
//
// FEATURES
//   - Receives Web Push notifications
//   - Displays emergency notifications
//   - Strong vibration for HIGH / CRITICAL alerts
//   - Notification click navigation
//   - Reuses existing citizen window when possible
//   - Opens citizen portal when no window exists
//   - Supports informational notifications
//   - Supports emergency alarm metadata
//   - Supports notification action button
//   - Safe fallback for plain-text push payloads
//
// IMPORTANT
//   A browser service worker cannot reliably force audio
//   playback while a page is in the background.
//
//   Therefore:
//     1. This worker shows the notification.
//     2. This worker requests vibration where supported.
//     3. The citizen page can play an audible alarm when it
//        is open and the browser permits audio playback.
//
// ============================================================

"use strict";


// ============================================================
// CONFIGURATION
// ============================================================

const SW_VERSION = "13.0.0";

const DEFAULT_URL =
    "/citizen/";

const CITIZEN_URL =
    "/citizen/";

const ICON_URL =
    "/citizen/icon-192.png";

const BADGE_URL =
    "/citizen/icon-192.png";

const NORMAL_VIBRATION = [
    200,
    100,
    200,
];

const MEDIUM_VIBRATION = [
    350,
    150,
    350,
];

const HIGH_VIBRATION = [
    500,
    120,
    500,
    120,
    500,
    120,
    700,
];


// ============================================================
// INSTALL
// ============================================================

self.addEventListener(
    "install",
    event => {

        console.log(
            `[EWS SW ${SW_VERSION}] Installing...`
        );

        // Activate the newest service worker immediately.
        self.skipWaiting();

    }
);


// ============================================================
// ACTIVATE
// ============================================================

self.addEventListener(
    "activate",
    event => {

        console.log(
            `[EWS SW ${SW_VERSION}] Activating...`
        );

        event.waitUntil(

            self.clients.claim()

                .then(
                    () => {

                        console.log(
                            `[EWS SW ${SW_VERSION}] Active.`
                        );

                    }
                )

        );

    }
);


// ============================================================
// PUSH EVENT
// ============================================================

self.addEventListener(
    "push",
    event => {

        event.waitUntil(
            handlePushEvent(event)
        );

    }
);


// ============================================================
// HANDLE PUSH
// ============================================================

async function handlePushEvent(
    event
) {

    let payload = {};


    // --------------------------------------------------------
    // Read the push payload safely.
    // --------------------------------------------------------

    if (event.data) {

        try {

            payload =
                event.data.json();

        } catch (jsonError) {

            console.warn(
                "[EWS SW] Push JSON parsing failed:",
                jsonError
            );


            try {

                payload = {

                    title:
                        "🌊 Odisha Flood EWS",

                    body:
                        event.data.text(),

                    severity:
                        "INFO",

                    url:
                        DEFAULT_URL,

                    alarm_seconds:
                        3,

                    requireInteraction:
                        false,

                };

            } catch (textError) {

                console.warn(
                    "[EWS SW] Push text parsing failed:",
                    textError
                );


                payload = {

                    title:
                        "🌊 Odisha Flood EWS",

                    body:
                        "New emergency notification received.",

                    severity:
                        "INFO",

                    url:
                        DEFAULT_URL,

                    alarm_seconds:
                        3,

                    requireInteraction:
                        false,

                };

            }

        }

    } else {

        payload = {

            title:
                "🌊 Odisha Flood EWS",

            body:
                "New emergency notification received.",

            severity:
                "INFO",

            url:
                DEFAULT_URL,

            alarm_seconds:
                3,

            requireInteraction:
                false,

        };

    }


    // --------------------------------------------------------
    // Normalize values.
    // --------------------------------------------------------

    const title =
        cleanText(
            payload.title,
            "🌊 Odisha Flood EWS"
        );


    const body =
        cleanText(
            payload.body,
            "New emergency notification received."
        );


    const severity =
        normalizeSeverity(
            payload.severity
        );


    const area =
        cleanText(
            payload.area,
            "All areas"
        );


    const targetUrl =
        safeTargetUrl(
            payload.url
        );


    const alarmSeconds =
        normalizeAlarmSeconds(
            payload.alarm_seconds
        );


    const requireInteraction =
        payload.requireInteraction !== false;


    const notificationId =
        cleanText(
            payload.notification_id,
            payload.timestamp ||
            `${Date.now()}-${Math.random()}`
        );


    // --------------------------------------------------------
    // Build strong vibration pattern.
    // --------------------------------------------------------

    const vibration =
        vibrationForSeverity(
            severity
        );


    // --------------------------------------------------------
    // Build display body.
    // --------------------------------------------------------

    const displayBody =
        buildDisplayBody(
            body,
            area,
            severity
        );


    // --------------------------------------------------------
    // Build notification options.
    // --------------------------------------------------------

    const options = {

        body:
            displayBody,

        icon:
            ICON_URL,

        badge:
            BADGE_URL,

        tag:
            `ews-${notificationId}`,

        renotify:
            true,

        requireInteraction:
            requireInteraction,

        vibrate:
            vibration,

        timestamp:
            Date.now(),

        data:
            {

                url:
                    targetUrl,

                severity:
                    severity,

                area:
                    area,

                alarm_seconds:
                    alarmSeconds,

                timestamp:
                    payload.timestamp
                    ||
                    new Date().toISOString(),

                notification_id:
                    notificationId,

                type:
                    payload.type
                    ||
                    "EWS_NOTIFICATION",

            },

        actions:
            [

                {
                    action:
                        "open",

                    title:
                        "Open EWS",

                },

            ],

    };


    // --------------------------------------------------------
    // CRITICAL/HIGH additional visual emphasis.
    // --------------------------------------------------------

    if (
        severity === "CRITICAL"
        ||
        severity === "HIGH"
    ) {

        options.renotify = true;

        options.requireInteraction = true;

    }


    // --------------------------------------------------------
    // Show notification.
    // --------------------------------------------------------

    try {

        await self.registration.showNotification(
            title,
            options
        );


        console.log(
            `[EWS SW] Notification shown: ${notificationId}`
        );


    } catch (error) {

        console.error(
            "[EWS SW] Could not show notification:",
            error
        );

    }

}


// ============================================================
// CLEAN TEXT
// ============================================================

function cleanText(
    value,
    fallback
) {

    if (
        value === null
        ||
        value === undefined
    ) {

        return fallback;

    }


    const result =
        String(
            value
        ).trim();


    return result ||
        fallback;

}


// ============================================================
// NORMALIZE SEVERITY
// ============================================================

function normalizeSeverity(
    value
) {

    const severity =
        String(
            value
            ||
            "INFO"
        )
        .trim()
        .toUpperCase();


    if (
        severity === "CRITICAL"
        ||
        severity === "HIGH"
        ||
        severity === "MEDIUM"
        ||
        severity === "LOW"
        ||
        severity === "INFO"
    ) {

        return severity;

    }


    return "INFO";

}


// ============================================================
// VIBRATION
// ============================================================

function vibrationForSeverity(
    severity
) {

    if (
        severity === "CRITICAL"
    ) {

        return [

            700,
            120,
            700,
            120,
            700,
            120,
            1000,
            150,
            1000,

        ];

    }


    if (
        severity === "HIGH"
    ) {

        return HIGH_VIBRATION;

    }


    if (
        severity === "MEDIUM"
    ) {

        return MEDIUM_VIBRATION;

    }


    return NORMAL_VIBRATION;

}


// ============================================================
// ALARM SECONDS
// ============================================================

function normalizeAlarmSeconds(
    value
) {

    const number =
        Number(
            value
        );


    if (
        !Number.isFinite(
            number
        )
    ) {

        return 0;

    }


    return Math.max(

        0,

        Math.min(

            Math.round(
                number
            ),

            30

        )

    );

}


// ============================================================
// TARGET URL
// ============================================================

function safeTargetUrl(
    value
) {

    try {

        const candidate =
            new URL(

                value
                ||
                DEFAULT_URL,

                self.location.origin

            );


        // Only permit navigation inside this
        // application's origin.
        if (
            candidate.origin
            !==
            self.location.origin
        ) {

            return
                new URL(
                    DEFAULT_URL,
                    self.location.origin
                ).href;

        }


        return candidate.href;

    } catch {

        return
            new URL(
                DEFAULT_URL,
                self.location.origin
            ).href;

    }

}


// ============================================================
// DISPLAY BODY
// ============================================================

function buildDisplayBody(
    body,
    area,
    severity
) {

    let result =
        body;


    // Keep normal messages readable.
    if (
        area
        &&
        area.toLowerCase()
            !==
            "all areas"
    ) {

        result +=
            `\n\nArea: ${area}`;

    }


    if (
        severity === "CRITICAL"
    ) {

        result =
            "🚨 CRITICAL EMERGENCY\n\n"
            +
            result;

    } else if (
        severity === "HIGH"
    ) {

        result =
            "⚠️ HIGH PRIORITY ALERT\n\n"
            +
            result;

    }


    return result;

}


// ============================================================
// NOTIFICATION CLICK
// ============================================================

self.addEventListener(
    "notificationclick",
    event => {

        event.notification.close();


        event.waitUntil(

            openNotificationTarget(
                event
            )

        );

    }
);


// ============================================================
// OPEN NOTIFICATION TARGET
// ============================================================

async function openNotificationTarget(
    event
) {

    const notification =
        event.notification
        ||
        {};


    const data =
        notification.data
        ||
        {};


    let targetUrl =
        safeTargetUrl(
            data.url
        );


    // --------------------------------------------------------
    // Special action handling.
    // --------------------------------------------------------

    if (
        event.action
        ===
        "open"
    ) {

        targetUrl =
            safeTargetUrl(
                data.url
                ||
                CITIZEN_URL
            );

    }


    // --------------------------------------------------------
    // Find already-open application windows.
    // --------------------------------------------------------

    const clientList =
        await self.clients.matchAll(

            {

                type:
                    "window",

                includeUncontrolled:
                    true,

            }

        );


    // --------------------------------------------------------
    // Prefer an existing citizen application.
    // --------------------------------------------------------

    for (
        const client
        of
        clientList
    ) {

        try {

            const clientUrl =
                new URL(
                    client.url
                );


            if (
                clientUrl.origin
                !==
                self.location.origin
            ) {

                continue;

            }


            // Reuse an existing citizen window.
            if (
                client.url.includes(
                    "/citizen"
                )
            ) {

                await client.focus();


                if (
                    typeof client.navigate
                    ===
                    "function"
                ) {

                    try {

                        await client.navigate(
                            targetUrl
                        );

                    } catch (navigationError) {

                        console.warn(
                            "[EWS SW] Existing-window navigation failed:",
                            navigationError
                        );

                    }

                }


                // Tell the active page that an emergency
                // notification was opened.
                try {

                    client.postMessage(

                        {

                            type:
                                "EWS_NOTIFICATION_OPENED",

                            notification:
                                data,

                        }

                    );

                } catch {

                    // Ignore messaging failure.

                }


                return;

            }

        } catch (error) {

            console.warn(
                "[EWS SW] Existing window inspection failed:",
                error
            );

        }

    }


    // --------------------------------------------------------
    // No existing citizen window.
    // --------------------------------------------------------

    if (
        self.clients.openWindow
    ) {

        try {

            await self.clients.openWindow(
                targetUrl
            );

        } catch (error) {

            console.error(
                "[EWS SW] Could not open notification target:",
                error
            );

        }

    }

}


// ============================================================
// NOTIFICATION CLOSE
// ============================================================

self.addEventListener(
    "notificationclose",
    event => {

        console.log(
            "[EWS SW] Notification closed."
        );

    }
);


// ============================================================
// MESSAGE FROM CITIZEN PAGE
// ============================================================

self.addEventListener(
    "message",
    event => {

        const data =
            event.data
            ||
            {};


        // ----------------------------------------------------
        // PING
        // ----------------------------------------------------

        if (
            data.type
            ===
            "PING"
        ) {

            if (
                event.source
                &&
                typeof event.source.postMessage
                ===
                "function"
            ) {

                event.source.postMessage(

                    {

                        type:
                            "PONG",

                        service_worker:
                            "odisha-flood-ews",

                        version:
                            SW_VERSION,

                    }

                );

            }

            return;

        }


        // ----------------------------------------------------
        // SKIP WAITING
        // ----------------------------------------------------

        if (
            data.type
            ===
            "SKIP_WAITING"
        ) {

            self.skipWaiting();

            return;

        }


        // ----------------------------------------------------
        // CLIENT HEALTH CHECK
        // ----------------------------------------------------

        if (
            data.type
            ===
            "GET_SW_STATUS"
        ) {

            if (
                event.source
                &&
                typeof event.source.postMessage
                ===
                "function"
            ) {

                event.source.postMessage(

                    {

                        type:
                            "SW_STATUS",

                        version:
                            SW_VERSION,

                        active:
                            true,

                        scope:
                            self.registration.scope,

                    }

                );

            }

            return;

        }

    }
);


// ============================================================
// FETCH
// ============================================================
//
// Emergency APIs should remain LIVE.
// We deliberately do not cache API responses here.
//
// Static resources may still be handled normally by the
// browser.
//
// ============================================================

self.addEventListener(
    "fetch",
    event => {

        // Intentionally network-default.
        //
        // Do NOT cache live emergency API responses here.

        return;

    }
);


// ============================================================
// DIAGNOSTIC
// ============================================================

console.log(
    `[EWS SW ${SW_VERSION}] Odisha Flood EWS service worker loaded.`
);