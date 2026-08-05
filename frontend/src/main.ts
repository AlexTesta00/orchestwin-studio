import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import "./app.css";
import { createAppI18n, defaultLocale } from "./i18n";
import { createAppRouter } from "./router";

const application = createApp(App);
const i18n = createAppI18n();

document.documentElement.lang = defaultLocale;

application.use(createPinia());
application.use(i18n);
application.use(createAppRouter());
application.mount("#app");
