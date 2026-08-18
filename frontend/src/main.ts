import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { apiClient } from "./api/client";
import { createAppI18n, defaultLocale } from "./i18n";
import { installAuthenticationGuard } from "./router/authentication";
import { createAppRouter } from "./router";
import "./styles/tailwind.css";

const application = createApp(App);
const pinia = createPinia();
const router = createAppRouter();
const i18n = createAppI18n();

document.documentElement.lang = defaultLocale;

installAuthenticationGuard(router, pinia, apiClient);

application.use(pinia);
application.use(i18n);
application.use(router);
application.mount("#app");
