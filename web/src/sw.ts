/// <reference lib="webworker" />
import { precacheAndRoute } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

self.addEventListener("push", (event) => {
  if (!event.data) return;

  const data = event.data.json();

  let title: string;
  let options: NotificationOptions;

  if (data.type === "alert") {
    const urgencyPrefix = data.urgency === "critical" ? "[CRITICAL] " : "";
    title = `${urgencyPrefix}Alert`;
    options = {
      body: `${data.label} — Value: ${data.trigger_value}`,
      icon: "/icon-192.png",
      tag: `alert-${data.alert_id}`,
      requireInteraction: data.urgency === "critical",
      data: { url: "/" },
    };
  } else {
    title = data.title ?? "Krypton";
    options = {
      body: data.body ?? "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: data.url || "/" },
    };
  }

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
