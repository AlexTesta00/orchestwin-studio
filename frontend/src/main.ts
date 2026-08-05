import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import "./app.css";
import { createAppRouter } from "./router";

const application = createApp(App);

application.use(createPinia());
application.use(createAppRouter());
application.mount("#app");
