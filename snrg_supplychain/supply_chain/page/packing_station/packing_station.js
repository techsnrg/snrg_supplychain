frappe.provide("snrg_supplychain.packing_station");

frappe.pages["packing_station"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Packing Station"),
		single_column: true,
	});

	snrg_supplychain.packing_station.init(wrapper, page);
};

frappe.pages["packing_station"].on_page_show = function (wrapper) {
	const controller = $(wrapper).data("controller");
	if (controller) {
		controller.refreshView();
	}
};

snrg_supplychain.packing_station.init = function (wrapper, page) {
	const controller = new snrg_supplychain.packing_station.Controller(wrapper, page);
	$(wrapper).data("controller", controller);
};

snrg_supplychain.packing_station.Controller = class PackingStationController {
	constructor(wrapper, page) {
		this.wrapper = $(wrapper);
		this.page = page;
		this.state = {
			mode: "home",
			activeStep: "details",
			doc: null,
			items: [],
			recentCartons: [],
			totals: {
				lines: 0,
				pieces: 0,
				net_weight_kg: 0,
				gross_weight_kg: 0,
			},
		};

		this.renderShell();
		this.bindActions();
		this.refreshView();
	}

	get routeToken() {
		return frappe.get_route()[1] || frappe.route_options?.name || "";
	}

	renderShell() {
		this.wrapper.find(".layout-main-section").html(`
			<div class="ps-app">
				<div class="ps-topbar">
					<div class="ps-topbar-left">
						<div class="ps-badge">${__("Packing Station")}</div>
						<div class="ps-heading">${__("Packed Carton Workflow")}</div>
					</div>
					<div class="ps-topbar-actions">
						<button class="btn btn-default ps-home-btn">${__("Home")}</button>
						<button class="btn btn-primary ps-new-btn">${__("New Carton")}</button>
					</div>
				</div>
				<div class="ps-home-view"></div>
				<div class="ps-editor-view"></div>
			</div>
		`);

		if (!document.getElementById("packing-station-style")) {
			$("head").append(`
				<style id="packing-station-style">
					.ps-app { min-height: calc(100vh - 92px); height: calc(100vh - 92px); overflow: hidden; background:#f1f4f8; color:#17212b; padding:8px; }
					.ps-topbar { display:flex; justify-content:space-between; align-items:center; gap:12px; background:#101927; color:#fff; border-radius:12px; padding:10px 12px; margin-bottom:8px; }
					.ps-topbar-left { min-width:0; }
					.ps-badge { font-size:10px; text-transform:uppercase; letter-spacing:.12em; color:#8fa2bb; font-weight:700; }
					.ps-heading { font-size:20px; font-weight:900; line-height:1.1; margin-top:2px; }
					.ps-topbar-actions, .ps-action-row, .ps-home-actions, .ps-review-actions, .ps-items-toolbar { display:flex; gap:8px; flex-wrap:wrap; }
					.ps-topbar-actions .btn, .ps-action-row .btn, .ps-home-actions .btn, .ps-review-actions .btn, .ps-items-toolbar .btn { min-height:36px; border-radius:10px; font-size:13px; font-weight:800; padding:0 12px; }
					.ps-home-btn { background:#233245; color:#fff; border-color:#233245; }
					.ps-layout { display:grid; grid-template-columns:260px minmax(0, 1fr); gap:8px; height: calc(100vh - 148px); min-height:0; }
					.ps-sidebar, .ps-panel, .ps-shell-card { background:#fff; border:1px solid #d9e1ea; border-radius:12px; padding:10px; }
					.ps-sidebar { display:grid; gap:8px; align-content:start; }
					.ps-step-nav { display:grid; gap:6px; }
					.ps-step-btn { width:100%; text-align:left; border:1px solid #d9e1ea; background:#f7f9fb; border-radius:12px; padding:12px; }
					.ps-step-btn.is-active { background:#0f6cbd; border-color:#0f6cbd; color:#fff; }
					.ps-step-no { font-size:10px; text-transform:uppercase; letter-spacing:.1em; opacity:.75; }
					.ps-step-label { font-size:14px; font-weight:900; margin-top:2px; }
					.ps-step-copy { font-size:11px; margin-top:4px; color:inherit; opacity:.8; }
					.ps-mini-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; }
					.ps-mini-box { border:1px solid #d9e1ea; border-radius:10px; background:#f7f9fb; padding:8px; }
					.ps-mini-label { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:#66788a; font-weight:700; }
					.ps-mini-value { margin-top:2px; font-size:16px; font-weight:900; color:#17212b; }
					.ps-panel { display:grid; grid-template-rows:auto 1fr; min-height:0; }
					.ps-panel-header { display:flex; justify-content:space-between; gap:8px; align-items:center; margin-bottom:8px; }
					.ps-panel-title { font-size:17px; font-weight:900; }
					.ps-panel-copy { font-size:12px; color:#66788a; }
					.ps-step-host { min-height:0; overflow:auto; }
					.ps-form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
					.ps-field .control-label { font-size:10px; font-weight:700; color:#5b6b7c; margin-bottom:4px; }
					.ps-field .control-input-wrapper input,
					.ps-field .control-input-wrapper .control-value,
					.ps-field .control-input-wrapper .awesomplete input,
					.ps-field .control-input-wrapper select {
						min-height:38px; border-radius:10px; font-size:15px; font-weight:700; background:#f7f9fb; border-color:#d9e1ea;
					}
					.ps-inline-note { font-size:12px; color:#66788a; margin-top:8px; }
					.ps-checklist { display:grid; gap:8px; }
					.ps-checkitem { display:flex; gap:8px; align-items:flex-start; border:1px solid #d9e1ea; border-radius:10px; background:#f7f9fb; padding:8px; }
					.ps-dot { width:10px; height:10px; margin-top:4px; border-radius:999px; background:#c7d2de; }
					.ps-dot.is-done { background:#149954; }
					.ps-checktext { font-size:12px; color:#445261; }
					.ps-items-toolbar { margin-bottom:8px; }
					.ps-items-table { border:1px solid #d9e1ea; border-radius:12px; overflow:hidden; }
					.ps-items-head, .ps-item-row { display:grid; grid-template-columns:minmax(0,2fr) 82px 96px 160px; gap:8px; align-items:center; padding:8px 10px; }
					.ps-items-head { background:#f7f9fb; font-size:10px; text-transform:uppercase; letter-spacing:.08em; font-weight:800; color:#66788a; }
					.ps-item-row { border-top:1px solid #eef2f6; background:#fff; }
					.ps-item-main { min-width:0; }
					.ps-item-code { font-size:14px; font-weight:900; color:#17212b; }
					.ps-item-name { font-size:12px; color:#66788a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
					.ps-item-qty { display:flex; gap:6px; align-items:center; }
					.ps-qty-btn { min-width:30px; min-height:30px; border:none; border-radius:8px; background:#1173d4; color:#fff; font-size:18px; font-weight:900; }
					.ps-qty-value { min-width:34px; text-align:center; font-size:16px; font-weight:900; border:1px solid #d9e1ea; border-radius:8px; background:#f7f9fb; padding:4px 6px; }
					.ps-item-meta { font-size:12px; color:#445261; font-weight:700; }
					.ps-empty { border:1px dashed #b8c5d3; border-radius:10px; background:#f7f9fb; padding:18px; text-align:center; font-size:13px; font-weight:700; color:#66788a; }
					.ps-review-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-bottom:10px; }
					.ps-review-box { border:1px solid #d9e1ea; border-radius:10px; background:#f7f9fb; padding:10px; }
					.ps-review-label { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:#66788a; font-weight:700; }
					.ps-review-value { font-size:18px; font-weight:900; color:#17212b; margin-top:4px; }
					.ps-review-meta { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-bottom:10px; }
					.ps-meta-card { border:1px solid #d9e1ea; border-radius:10px; background:#fff; padding:10px; }
					.ps-meta-line { display:flex; justify-content:space-between; gap:8px; font-size:12px; padding:4px 0; border-bottom:1px solid #eef2f6; }
					.ps-meta-line:last-child { border-bottom:none; }
					.ps-home-layout { display:grid; grid-template-columns:320px minmax(0,1fr); gap:8px; height: calc(100vh - 148px); min-height:0; }
					.ps-home-stack { display:grid; gap:8px; align-content:start; }
					.ps-home-title { font-size:18px; font-weight:900; margin-bottom:4px; }
					.ps-home-copy { font-size:12px; color:#66788a; margin-bottom:8px; }
					.ps-tile-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
					.ps-tile { border:none; border-radius:14px; min-height:118px; padding:14px; color:#fff; text-align:left; display:flex; flex-direction:column; justify-content:space-between; }
					.ps-tile-title { font-size:16px; font-weight:900; line-height:1.1; }
					.ps-tile-copy { font-size:11px; line-height:1.35; opacity:.9; }
					.ps-tile--blue { background:#0f6cbd; }
					.ps-tile--teal { background:#0a9396; }
					.ps-tile--violet { background:#7b2cbf; }
					.ps-tile--orange { background:#ee6c4d; }
					.ps-search-row { display:flex; gap:8px; }
					.ps-search-row input { min-height:38px; border-radius:10px; font-size:14px; font-weight:700; background:#f7f9fb; }
					.ps-recent-list { display:grid; gap:6px; overflow:auto; align-content:start; }
					.ps-recent-card { border:1px solid #d9e1ea; border-radius:10px; background:#fff; padding:10px; cursor:pointer; }
					.ps-recent-card:hover { background:#f7f9fb; }
					.ps-recent-top { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }
					.ps-recent-name { font-size:14px; font-weight:900; }
					.ps-recent-pill { min-height:22px; padding:0 8px; border-radius:999px; background:#ebf5ee; color:#0f6a34; font-size:10px; font-weight:800; display:inline-flex; align-items:center; }
					.ps-recent-meta { margin-top:4px; display:grid; gap:2px; font-size:11px; color:#66788a; }
					.ps-editor-view.is-hidden, .ps-home-view.is-hidden { display:none; }
					@media (max-width: 1100px) {
						.ps-app { height:auto; overflow:auto; }
						.ps-layout, .ps-home-layout { height:auto; grid-template-columns:1fr; }
					}
					@media (max-width: 800px) {
						.ps-topbar { grid-template-columns:1fr; display:grid; align-items:start; }
						.ps-form-grid, .ps-review-grid, .ps-review-meta { grid-template-columns:1fr; }
						.ps-items-head, .ps-item-row { grid-template-columns:1fr; }
						.ps-tile-grid { grid-template-columns:1fr; }
						.ps-topbar-actions .btn, .ps-action-row .btn, .ps-home-actions .btn, .ps-review-actions .btn, .ps-items-toolbar .btn { flex:1 1 100%; }
						.ps-search-row { flex-direction:column; }
					}
				</style>
			`);
		}

		this.$homeView = this.wrapper.find(".ps-home-view");
		this.$editorView = this.wrapper.find(".ps-editor-view");
	}

	bindActions() {
		this.wrapper.on("click", ".ps-home-btn", () => this.goHome());
		this.wrapper.on("click", ".ps-new-btn", () => this.startNew());
		this.wrapper.on("click", ".ps-home-open-form", () => this.openStandardForm());
		this.wrapper.on("click", ".ps-step-btn", (e) => this.setStep($(e.currentTarget).data("step")));
		this.wrapper.on("click", ".ps-resume-btn", () => this.openExistingDialog());
		this.wrapper.on("click", ".ps-recent-card", (e) => this.openRecent($(e.currentTarget).data("name")));
		this.wrapper.on("click", ".ps-search-btn", () => this.searchRecent());
		this.wrapper.on("keydown", ".ps-search-input", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				this.searchRecent();
			}
		});
		this.wrapper.on("click", ".ps-next-items", () => this.setStep("items"));
		this.wrapper.on("click", ".ps-next-review", () => this.setStep("review"));
		this.wrapper.on("click", ".ps-back-details", () => this.setStep("details"));
		this.wrapper.on("click", ".ps-back-items", () => this.setStep("items"));
		this.wrapper.on("click", ".ps-add-item", () => this.openAddItemDialog());
		this.wrapper.on("click", ".ps-clear-items", () => this.clearItems());
		this.wrapper.on("click", ".ps-open-form", () => this.openStandardForm());
		this.wrapper.on("click", ".ps-save", () => this.saveDoc());
		this.wrapper.on("click", ".ps-save-print", async () => {
			await this.saveDoc();
			this.printDoc();
		});
		this.wrapper.on("click", ".ps-qty-btn", (e) => this.adjustQty(e));
		this.wrapper.on("click", ".ps-remove-item", (e) => this.removeItem(e));
	}

	async refreshView() {
		const token = this.routeToken;
		if (!token) {
			this.state.mode = "home";
			await this.loadHome();
			return;
		}

		this.state.mode = "editor";
		this.state.activeStep = token === "new" ? "details" : "items";
		await this.loadDoc(token === "new" ? null : token);
	}

	async loadHome(searchText = "") {
		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.list_touch_cartons",
			args: { search_text: searchText || null, limit: 14 },
			freeze: true,
			freeze_message: __("Loading cartons..."),
		});

		this.state.recentCartons = response.message || [];
		this.renderHome();
	}

	renderHome() {
		this.page.set_title(__("Packing Station"));
		this.$editorView.addClass("is-hidden").empty();
		this.$homeView.removeClass("is-hidden").html(`
			<div class="ps-home-layout">
				<div class="ps-home-stack">
					<div class="ps-shell-card">
						<div class="ps-home-title">${__("Start Work")}</div>
						<div class="ps-home-copy">${__("Use the station like a handheld device. Tap a tile to begin.")}</div>
						<div class="ps-tile-grid">
							<button class="ps-tile ps-tile--blue ps-new-btn">
								<div class="ps-tile-title">${__("New Carton")}</div>
								<div class="ps-tile-copy">${__("Start a fresh packing workflow")}</div>
							</button>
							<button class="ps-tile ps-tile--teal ps-resume-btn">
								<div class="ps-tile-title">${__("Resume")}</div>
								<div class="ps-tile-copy">${__("Open an existing carton and continue work")}</div>
							</button>
							<button class="ps-tile ps-tile--violet ps-search-btn">
								<div class="ps-tile-title">${__("Search")}</div>
								<div class="ps-tile-copy">${__("Find carton by number from the search box below")}</div>
							</button>
							<button class="ps-tile ps-tile--orange ps-home-open-form">
								<div class="ps-tile-title">${__("Admin Form")}</div>
								<div class="ps-tile-copy">${__("Open the normal ERP form when needed")}</div>
							</button>
						</div>
					</div>
					<div class="ps-shell-card">
						<div class="ps-home-title">${__("Search")}</div>
						<div class="ps-search-row">
							<input class="form-control ps-search-input" type="text" placeholder="${__("Search carton number")}" />
							<button class="btn btn-default ps-search-btn">${__("Search")}</button>
						</div>
					</div>
				</div>
				<div class="ps-shell-card ps-panel">
					<div class="ps-panel-header">
						<div>
							<div class="ps-panel-title">${__("Recent Cartons")}</div>
							<div class="ps-panel-copy">${__("Tap a carton to reopen its workflow.")}</div>
						</div>
					</div>
					<div class="ps-step-host">
						<div class="ps-recent-list"></div>
					</div>
				</div>
			</div>
		`);

		const $list = this.wrapper.find(".ps-recent-list");
		if (!this.state.recentCartons.length) {
			$list.html(`<div class="ps-empty">${__("No cartons yet. Start a new carton to begin packing.")}</div>`);
			return;
		}

		$list.html(this.state.recentCartons.map((carton) => `
			<div class="ps-recent-card" data-name="${frappe.utils.escape_html(carton.name)}">
				<div class="ps-recent-top">
					<div class="ps-recent-name">${frappe.utils.escape_html(carton.name)}</div>
					<div class="ps-recent-pill">${frappe.utils.escape_html(carton.status || __("Available"))}</div>
				</div>
				<div class="ps-recent-meta">
					<div>${__("Box Type")}: ${frappe.utils.escape_html(carton.box_type || "-")}</div>
					<div>${__("Packed Date")}: ${frappe.datetime.str_to_user(carton.packed_date || "") || "-"}</div>
					<div>${__("Warehouse")}: ${frappe.utils.escape_html(carton.warehouse || "-")}</div>
				</div>
			</div>
		`).join(""));
	}

	async loadDoc(docname = null) {
		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.get_touch_carton",
			args: { name: docname || null },
			freeze: true,
			freeze_message: __("Loading carton..."),
		});

		this.state.doc = response.message;
		this.state.items = (response.message.items || []).map((item) => ({ ...item }));
		this.renderEditor();
		this.renderStep();
	}

	renderEditor() {
		this.page.set_title(this.state.doc?.name || __("New Carton"));
		this.$homeView.addClass("is-hidden").empty();
		this.$editorView.removeClass("is-hidden").html(`
			<div class="ps-layout">
				<aside class="ps-sidebar">
					<div class="ps-step-nav"></div>
					<div class="ps-shell-card">
						<div class="ps-card-title">${__("Current Carton")}</div>
						<div style="font-size:18px;font-weight:900;">${frappe.utils.escape_html(this.state.doc?.name || __("Not Saved"))}</div>
						<div class="ps-inline-note">${this.state.doc?.box_type ? frappe.utils.escape_html(this.state.doc.box_type) : __("Choose box type in Step 1")}</div>
					</div>
					<div class="ps-mini-grid">
						<div class="ps-mini-box"><div class="ps-mini-label">${__("Lines")}</div><div class="ps-mini-value" data-mini="lines">0</div></div>
						<div class="ps-mini-box"><div class="ps-mini-label">${__("Qty")}</div><div class="ps-mini-value" data-mini="pieces">0</div></div>
						<div class="ps-mini-box"><div class="ps-mini-label">${__("Net")}</div><div class="ps-mini-value" data-mini="net">0</div></div>
						<div class="ps-mini-box"><div class="ps-mini-label">${__("Gross")}</div><div class="ps-mini-value" data-mini="gross">0</div></div>
					</div>
				</aside>
				<section class="ps-panel">
					<div class="ps-panel-header">
						<div>
							<div class="ps-panel-title"></div>
							<div class="ps-panel-copy"></div>
						</div>
						<div class="ps-action-row">
							<button class="btn btn-default ps-open-form">${__("Open Form")}</button>
						</div>
					</div>
					<div class="ps-step-host"></div>
				</section>
			</div>
		`);
	}

	renderStepNav() {
		const steps = [
			{ key: "details", no: "01", label: __("Details"), copy: __("Set carton basics") },
			{ key: "items", no: "02", label: __("Items"), copy: __("Build the carton") },
			{ key: "review", no: "03", label: __("Review"), copy: __("Save and print") },
		];
		this.wrapper.find(".ps-step-nav").html(steps.map((step) => `
			<button class="ps-step-btn ${this.state.activeStep === step.key ? "is-active" : ""}" data-step="${step.key}">
				<div class="ps-step-no">${step.no}</div>
				<div class="ps-step-label">${step.label}</div>
				<div class="ps-step-copy">${step.copy}</div>
			</button>
		`).join(""));
	}

	renderStep() {
		if (!this.state.doc) return;
		this.computeTotals();
		this.renderStepNav();
		this.renderMiniTotals();

		if (this.state.activeStep === "details") {
			this.renderDetailsStep();
			return;
		}
		if (this.state.activeStep === "items") {
			this.syncDocFromControls();
			this.renderItemsStep();
			return;
		}
		this.syncDocFromControls();
		this.renderReviewStep();
	}

	renderPanelHeader(title, copy) {
		this.wrapper.find(".ps-panel-title").text(title);
		this.wrapper.find(".ps-panel-copy").text(copy);
	}

	renderDetailsStep() {
		this.renderPanelHeader(__("Step 1: Carton Details"), __("Set the carton basics before adding items."));
		this.wrapper.find(".ps-step-host").html(`
			<div class="ps-form-grid">
				<div class="ps-field" data-field="name"></div>
				<div class="ps-field" data-field="box_type"></div>
				<div class="ps-field" data-field="packed_date"></div>
				<div class="ps-field" data-field="warehouse"></div>
				<div class="ps-field" data-field="packed_by"></div>
				<div class="ps-field" data-field="status"></div>
			</div>
			<div class="ps-inline-note">${__("Dimensions and box weight will auto-fill from the selected carton type.")}</div>
			<div class="ps-action-row" style="margin-top:10px;">
				<button class="btn btn-primary ps-next-items">${__("Continue to Items")}</button>
			</div>
		`);
		this.renderControls();
	}

	renderItemsStep() {
		this.renderPanelHeader(__("Step 2: Add Items"), __("Build the carton contents before final review."));
		const $host = this.wrapper.find(".ps-step-host");
		$host.html(`
			<div class="ps-items-toolbar">
				<button class="btn btn-primary ps-add-item">${__("Add Item")}</button>
				<button class="btn btn-default ps-clear-items">${__("Clear All")}</button>
				<button class="btn btn-default ps-back-details">${__("Back")}</button>
				<button class="btn btn-primary ps-next-review">${__("Review Carton")}</button>
			</div>
			<div class="ps-items-table">
				<div class="ps-items-head">
					<div>${__("Item")}</div>
					<div>${__("Qty")}</div>
					<div>${__("UOM / Wt")}</div>
					<div>${__("Actions")}</div>
				</div>
				<div class="ps-items-body"></div>
			</div>
		`);
		this.renderItemRows();
	}

	renderReviewStep() {
		this.renderPanelHeader(__("Step 3: Review & Save"), __("Verify totals, carton details, and then save or print."));
		this.wrapper.find(".ps-step-host").html(`
			<div class="ps-review-grid">
				<div class="ps-review-box"><div class="ps-review-label">${__("Lines")}</div><div class="ps-review-value">${this.state.totals.lines}</div></div>
				<div class="ps-review-box"><div class="ps-review-label">${__("Total Qty")}</div><div class="ps-review-value">${this.state.totals.pieces}</div></div>
				<div class="ps-review-box"><div class="ps-review-label">${__("Net Weight")}</div><div class="ps-review-value">${this.state.totals.net_weight_kg.toFixed(3)} kg</div></div>
				<div class="ps-review-box"><div class="ps-review-label">${__("Gross Weight")}</div><div class="ps-review-value">${this.state.totals.gross_weight_kg.toFixed(3)} kg</div></div>
			</div>
			<div class="ps-review-meta">
				<div class="ps-meta-card">
					<div class="ps-meta-line"><span>${__("Carton")}</span><strong>${frappe.utils.escape_html(this.state.doc.name || __("Not Saved"))}</strong></div>
					<div class="ps-meta-line"><span>${__("Box Type")}</span><strong>${frappe.utils.escape_html(this.state.doc.box_type || "-")}</strong></div>
					<div class="ps-meta-line"><span>${__("Warehouse")}</span><strong>${frappe.utils.escape_html(this.state.doc.warehouse || "-")}</strong></div>
					<div class="ps-meta-line"><span>${__("Packed Date")}</span><strong>${frappe.datetime.str_to_user(this.state.doc.packed_date || "") || "-"}</strong></div>
				</div>
				<div class="ps-meta-card">
					<div class="ps-meta-line"><span>${__("Dimensions")}</span><strong>${frappe.utils.escape_html(this.state.doc.dimensions || "-")}</strong></div>
					<div class="ps-meta-line"><span>${__("Empty Box")}</span><strong>${flt(this.state.doc.empty_weight_g || 0).toFixed(0)} g</strong></div>
					<div class="ps-meta-line"><span>${__("Packed By")}</span><strong>${frappe.utils.escape_html(this.state.doc.packed_by || "-")}</strong></div>
					<div class="ps-meta-line"><span>${__("Status")}</span><strong>${frappe.utils.escape_html(this.state.doc.status || __("Available"))}</strong></div>
				</div>
			</div>
			<div class="ps-checklist">
				${this.checkItem(!!this.state.doc.box_type, __("Box type selected"))}
				${this.checkItem(!!this.state.doc.warehouse, __("Warehouse selected"))}
				${this.checkItem(!!this.state.items.length, __("At least one item added"))}
			</div>
			<div class="ps-review-actions" style="margin-top:10px;">
				<button class="btn btn-default ps-back-items">${__("Back to Items")}</button>
				<button class="btn btn-default ps-save">${__("Save Carton")}</button>
				<button class="btn btn-primary ps-save-print">${__("Save & Print")}</button>
			</div>
		`);
	}

	checkItem(done, text) {
		return `<div class="ps-checkitem"><div class="ps-dot ${done ? "is-done" : ""}"></div><div class="ps-checktext">${frappe.utils.escape_html(text)}</div></div>`;
	}

	renderControls() {
		const fields = [
			{ fieldname: "name", label: __("Carton ID"), fieldtype: "Data", read_only: 1 },
			{ fieldname: "box_type", label: __("Box Type"), fieldtype: "Link", options: "Carton Type", reqd: 1 },
			{ fieldname: "packed_date", label: __("Packed Date"), fieldtype: "Date", reqd: 1 },
			{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1 },
			{ fieldname: "packed_by", label: __("Packed By"), fieldtype: "Link", options: "Employee" },
			{ fieldname: "status", label: __("Status"), fieldtype: "Data", read_only: 1 },
		];

		this.controls = {};
		fields.forEach((df) => {
			const container = this.wrapper.find(`.ps-field[data-field="${df.fieldname}"]`);
			const control = frappe.ui.form.make_control({
				parent: container,
				df: {
					...df,
					change: () => this.onFieldChange(df.fieldname),
				},
				render_input: true,
			});
			control.set_value(this.state.doc[df.fieldname] || "");
			if (df.read_only) {
				control.df.read_only = 1;
				control.refresh();
			}
			this.controls[df.fieldname] = control;
		});
	}

	syncDocFromControls() {
		if (!this.controls) return;
		["box_type", "packed_date", "warehouse", "packed_by"].forEach((fieldname) => {
			if (this.controls[fieldname]) {
				this.state.doc[fieldname] = this.controls[fieldname].get_value();
			}
		});
	}

	onFieldChange(fieldname) {
		this.syncDocFromControls();
		if (fieldname === "box_type") {
			if (!this.state.doc.box_type) {
				this.state.doc.dimensions = "";
				this.state.doc.empty_weight_g = 0;
				this.renderMiniTotals();
				return;
			}
			frappe.db.get_doc("Carton Type", this.state.doc.box_type).then((doc) => {
				this.state.doc.dimensions = `${doc.length_in} × ${doc.width_in} × ${doc.height_in} in`;
				this.state.doc.empty_weight_g = doc.empty_weight_g || 0;
				this.renderMiniTotals();
			});
		}
	}

	computeTotals() {
		const net = this.state.items.reduce((sum, item) => sum + (flt(item.qty) * flt(item.item_weight_kg)), 0);
		const pieces = this.state.items.reduce((sum, item) => sum + flt(item.qty), 0);
		const emptyWeight = flt(this.state.doc?.empty_weight_g || 0) / 1000;
		this.state.totals = {
			lines: this.state.items.length,
			pieces,
			net_weight_kg: parseFloat(net.toFixed(3)),
			gross_weight_kg: parseFloat((net + emptyWeight).toFixed(3)),
		};
		if (this.state.doc) {
			this.state.doc.net_weight_kg = this.state.totals.net_weight_kg;
			this.state.doc.gross_weight_kg = this.state.totals.gross_weight_kg;
		}
	}

	renderMiniTotals() {
		this.computeTotals();
		this.wrapper.find('[data-mini="lines"]').text(this.state.totals.lines);
		this.wrapper.find('[data-mini="pieces"]').text(this.state.totals.pieces);
		this.wrapper.find('[data-mini="net"]').text(this.state.totals.net_weight_kg.toFixed(3));
		this.wrapper.find('[data-mini="gross"]').text(this.state.totals.gross_weight_kg.toFixed(3));
	}

	renderItemRows() {
		const $body = this.wrapper.find(".ps-items-body");
		if (!$body.length) return;
		if (!this.state.items.length) {
			$body.html(`<div class="ps-empty" style="margin:8px;">${__("No items added yet. Use 'Add Item' to start building the carton.")}</div>`);
			return;
		}
		$body.html(this.state.items.map((item, index) => `
			<div class="ps-item-row">
				<div class="ps-item-main">
					<div class="ps-item-code">${frappe.utils.escape_html(item.item_code)}</div>
					<div class="ps-item-name">${frappe.utils.escape_html(item.item_name || "")}</div>
				</div>
				<div class="ps-item-qty">
					<button class="ps-qty-btn" data-direction="-1" data-index="${index}">-</button>
					<div class="ps-qty-value">${flt(item.qty)}</div>
					<button class="ps-qty-btn" data-direction="1" data-index="${index}">+</button>
				</div>
				<div class="ps-item-meta">
					<div>${frappe.utils.escape_html(item.uom || "")}</div>
					<div>${flt(item.item_weight_kg).toFixed(3)} kg/${__("unit")}</div>
				</div>
				<div class="ps-action-row">
					<button class="btn btn-default ps-remove-item" data-index="${index}">${__("Remove")}</button>
				</div>
			</div>
		`).join(""));
		this.renderMiniTotals();
	}

	setStep(step) {
		this.state.activeStep = step;
		this.renderStep();
	}

	startNew() {
		frappe.set_route("packing_station", "new");
	}

	goHome() {
		frappe.set_route("packing_station");
	}

	openRecent(name) {
		if (name) {
			frappe.set_route("packing_station", name);
		}
	}

	searchRecent() {
		const searchText = (this.wrapper.find(".ps-search-input").val() || "").trim();
		this.loadHome(searchText);
	}

	openExistingDialog() {
		const d = new frappe.ui.Dialog({
			title: __("Open Existing Carton"),
			fields: [
				{
					fieldname: "carton_name",
					fieldtype: "Link",
					label: __("Packed Carton"),
					options: "Packed Carton",
					reqd: 1,
				},
			],
			primary_action_label: __("Open"),
			primary_action: (values) => {
				frappe.set_route("packing_station", values.carton_name);
				d.hide();
			},
		});
		d.show();
	}

	async openAddItemDialog() {
		const d = new frappe.ui.Dialog({
			title: __("Add Item"),
			fields: [
				{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), reqd: 1 },
				{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), reqd: 1, default: 1 },
			],
			primary_action_label: __("Add"),
			primary_action: async (values) => {
				if (!values.item_code || !(values.qty > 0)) {
					frappe.show_alert({ indicator: "orange", message: __("Choose an item and enter a valid quantity.") });
					return;
				}
				const response = await frappe.call({
					method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.get_touch_item",
					args: { item_code: values.item_code },
				});
				const item = response.message;
				const existing = this.state.items.find((row) => row.item_code === item.item_code);
				if (existing) {
					existing.qty = flt(existing.qty) + flt(values.qty);
				} else {
					this.state.items.push({
						item_code: item.item_code,
						item_name: item.item_name,
						uom: item.uom,
						item_weight_kg: item.item_weight_kg,
						qty: flt(values.qty),
					});
				}
				this.renderItemRows();
				d.hide();
			},
		});
		d.show();
	}

	adjustQty(event) {
		const $btn = $(event.currentTarget);
		const index = cint($btn.data("index"));
		const direction = cint($btn.data("direction"));
		const item = this.state.items[index];
		if (!item) return;
		item.qty = Math.max(1, flt(item.qty) + direction);
		this.renderItemRows();
	}

	removeItem(event) {
		const index = cint($(event.currentTarget).data("index"));
		this.state.items.splice(index, 1);
		this.renderItemRows();
	}

	clearItems() {
		if (!this.state.items.length) return;
		this.state.items = [];
		this.renderItemRows();
	}

	buildPayload() {
		this.syncDocFromControls();
		return {
			name: this.state.doc.name || null,
			box_type: this.state.doc.box_type,
			packed_date: this.state.doc.packed_date,
			warehouse: this.state.doc.warehouse,
			packed_by: this.state.doc.packed_by,
			items: this.state.items,
		};
	}

	async saveDoc() {
		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.save_touch_carton",
			args: { payload: JSON.stringify(this.buildPayload()) },
			freeze: true,
			freeze_message: __("Saving carton..."),
		});
		this.state.doc = response.message;
		this.state.items = (response.message.items || []).map((item) => ({ ...item }));
		if (this.state.doc.name && this.routeToken !== this.state.doc.name) {
			frappe.set_route("packing_station", this.state.doc.name);
		}
		frappe.show_alert({ indicator: "green", message: __(`${this.state.doc.name} saved`) });
		this.renderEditor();
		this.renderStep();
		return this.state.doc;
	}

	openStandardForm() {
		if (this.state.doc?.name) {
			frappe.set_route("Form", "Packed Carton", this.state.doc.name);
			return;
		}
		frappe.new_doc("Packed Carton");
	}

	printDoc() {
		if (!this.state.doc?.name) {
			frappe.show_alert({ indicator: "orange", message: __("Save the carton before printing.") });
			return;
		}
		const url = `/printview?doctype=Packed%20Carton&name=${encodeURIComponent(this.state.doc.name)}&format=Carton%20Sticker&no_letterhead=1&_lang=en`;
		window.open(url, "_blank");
	}
};
