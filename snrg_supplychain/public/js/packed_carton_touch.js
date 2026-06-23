frappe.provide("snrg_supplychain.packed_carton_touch");

frappe.pages["packed_carton_touch"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Packed Carton Touch"),
		single_column: true,
	});

	snrg_supplychain.packed_carton_touch.init(wrapper, page);
};

frappe.pages["packed_carton_touch"].on_page_show = function (wrapper) {
	const controller = $(wrapper).data("controller");
	if (controller) {
		controller.refreshView();
	}
};

snrg_supplychain.packed_carton_touch.init = function (wrapper, page) {
	const controller = new snrg_supplychain.packed_carton_touch.Controller(wrapper, page);
	$(wrapper).data("controller", controller);
};

snrg_supplychain.packed_carton_touch.Controller = class PackedCartonTouchController {
	constructor(wrapper, page) {
		this.wrapper = $(wrapper);
		this.page = page;
		this.state = {
			mode: "home",
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
		this.bindPageActions();
		this.refreshView();
	}

	get routeToken() {
		return frappe.get_route()[1] || frappe.route_options?.name || "";
	}

	get isEditorMode() {
		return this.state.mode === "new" || this.state.mode === "edit";
	}

	renderShell() {
		this.wrapper.find(".layout-main-section").html(`
			<div class="pct-touch">
				<div class="pct-hero">
					<div class="pct-brand-block">
						<div class="pct-kicker">${__("Packing Station")}</div>
						<h1 class="pct-title">${__("Packed Carton")}</h1>
					</div>
					<div class="pct-hero-actions">
						<button class="btn btn-default pct-go-home">${__("Home")}</button>
						<button class="btn btn-primary pct-new-carton">${__("New Carton")}</button>
						<button class="btn btn-default pct-open-form">${__("Open Standard Form")}</button>
					</div>
				</div>

				<div class="pct-home-view"></div>
				<div class="pct-editor-view"></div>
			</div>
		`);

		if (!document.getElementById("pct-touch-style")) {
			$("head").append(`
				<style id="pct-touch-style">
					.pct-touch { padding: 8px; background:#eef1f5; min-height: calc(100vh - 92px); height: calc(100vh - 92px); overflow: hidden; color:#17212b; }
					.pct-hero { display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:8px; background:#17212b; border-radius:14px; padding:10px 12px; color:#fff; }
					.pct-brand-block { min-width:0; }
					.pct-kicker { text-transform:uppercase; letter-spacing:.12em; font-size:10px; color:#8ba0b6; font-weight:700; }
					.pct-title { margin:2px 0 0; font-size:22px; line-height:1; font-weight:900; color:#fff; }
					.pct-hero-actions { display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }
					.pct-card { background:#fff; border:1px solid #d8e0ea; border-radius:14px; padding:10px; box-shadow:none; }
					.pct-card-title { font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.1em; color:#5b6b7c; margin-bottom:8px; }
					.pct-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
					.pct-field .control-label { font-size:10px; font-weight:700; color:#5b6b7c; margin-bottom:4px; }
					.pct-field .control-input-wrapper input,
					.pct-field .control-input-wrapper .control-value,
					.pct-field .control-input-wrapper .awesomplete input,
					.pct-field .control-input-wrapper select {
						min-height:38px; border-radius:10px; font-size:16px; font-weight:700; background:#f7f9fb; border-color:#d8e0ea;
					}
					.pct-summary-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
					.pct-summary-box { background:#f7f9fb; border:1px solid #d8e0ea; border-radius:12px; padding:8px; }
					.pct-summary-label { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:#66788a; font-weight:700; margin-bottom:4px; }
					.pct-summary-value { font-size:20px; font-weight:900; color:#17212b; }
					.pct-summary-meta { margin-top:8px; font-size:12px; color:#4d5c6b; display:grid; gap:4px; }
					.pct-action-row, .pct-footer-actions, .pct-launcher-actions { display:flex; flex-wrap:wrap; gap:8px; }
					.pct-action-row .btn, .pct-footer-actions .btn, .pct-open-form, .pct-go-home, .pct-new-carton, .pct-launcher-actions .btn { min-height:38px; border-radius:10px; font-size:14px; font-weight:800; padding:0 12px; }
					.pct-go-home, .pct-open-form { background:#243140; color:#fff; border-color:#243140; }
					.pct-items-list { display:grid; gap:6px; overflow:auto; padding-right:2px; align-content:start; }
					.pct-item-card { border:1px solid #d8e0ea; border-radius:12px; padding:8px 10px; background:#fff; display:grid; grid-template-columns:minmax(0,1.8fr) minmax(0,1fr) auto; gap:10px; align-items:center; }
					.pct-item-main { min-width:0; }
					.pct-item-code { font-size:15px; font-weight:900; color:#17212b; line-height:1.1; }
					.pct-item-name { font-size:12px; color:#4d5c6b; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
					.pct-item-meta { display:grid; gap:2px; color:#66788a; font-size:11px; font-weight:700; }
					.pct-item-actions { display:flex; justify-content:flex-end; gap:8px; align-items:center; }
					.pct-qty-controls { display:flex; gap:6px; align-items:center; }
					.pct-qty-btn { min-width:34px; min-height:34px; border:none; border-radius:8px; background:#1173d4; color:#fff; font-size:20px; font-weight:900; }
					.pct-qty-display { min-width:44px; text-align:center; font-size:18px; font-weight:900; color:#17212b; background:#f7f9fb; border:1px solid #d8e0ea; border-radius:8px; padding:4px 8px; }
					.pct-remove-item { min-height:34px; border-radius:8px; font-size:12px; font-weight:800; }
					.pct-empty-state { display:none; padding:14px; border:1px dashed #b6c3d1; border-radius:12px; text-align:center; font-size:14px; font-weight:700; color:#66788a; background:#f7f9fb; }
					.pct-empty-state.is-visible { display:block; }
					.pct-home-shell, .pct-editor-shell { display:grid; gap:10px; height: calc(100vh - 152px); min-height: 0; }
					.pct-home-shell { grid-template-columns: 320px minmax(0, 1fr); }
					.pct-editor-shell { grid-template-columns: 320px minmax(0, 1fr); }
					.pct-side-stack { display:grid; gap:10px; min-height:0; align-content:start; }
					.pct-main-panel { min-height:0; display:grid; }
					.pct-items-panel { display:grid; grid-template-rows:auto 1fr auto; min-height:0; }
					.pct-home-grid { display:grid; grid-template-columns:1fr; gap:10px; }
					.pct-launcher-title { font-size:18px; line-height:1.05; font-weight:900; color:#17212b; margin:0 0 6px; }
					.pct-launcher-copy { font-size:12px; color:#66788a; margin-bottom:8px; max-width:560px; }
					.pct-search-row { display:flex; gap:8px; margin-bottom:8px; }
					.pct-search-row input { min-height:38px; border-radius:10px; font-size:14px; font-weight:700; background:#f7f9fb; }
					.pct-recent-list { display:grid; gap:8px; overflow:auto; padding-right:4px; }
					.pct-recent-card { border:1px solid #d8e0ea; border-radius:12px; padding:8px 10px; background:#fff; cursor:pointer; }
					.pct-recent-card:hover { background:#f7f9fb; }
					.pct-recent-top { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
					.pct-recent-name { font-size:14px; font-weight:900; color:#17212b; }
					.pct-pill { display:inline-flex; align-items:center; gap:6px; min-height:24px; padding:0 8px; border-radius:999px; font-size:10px; font-weight:800; background:#ebf5ee; color:#0f6a34; }
					.pct-recent-meta { display:grid; gap:2px; margin-top:4px; font-size:11px; color:#66788a; }
					.pct-home-empty { padding:16px; border:1px dashed #b6c3d1; border-radius:12px; text-align:center; font-size:13px; font-weight:700; color:#66788a; background:#f7f9fb; }
					.pct-editor-view.is-hidden, .pct-home-view.is-hidden { display:none; }
					@media (max-width: 1100px) {
						.pct-touch { height:auto; min-height:calc(100vh - 92px); overflow:auto; }
						.pct-home-shell, .pct-editor-shell { height:auto; grid-template-columns:1fr; }
						.pct-items-panel, .pct-main-panel, .pct-side-stack, .pct-recent-list, .pct-items-list { min-height:auto; }
					}
					@media (max-width: 900px) {
						.pct-touch { padding:10px; }
						.pct-hero, .pct-fields, .pct-home-grid { grid-template-columns:1fr; display:grid; align-items:start; }
						.pct-title, .pct-launcher-title { font-size:20px; }
						.pct-fields { grid-template-columns:1fr; }
						.pct-summary-grid { grid-template-columns:1fr 1fr; }
						.pct-card { border-radius:12px; padding:8px; }
						.pct-action-row .btn, .pct-footer-actions .btn, .pct-hero-actions .btn, .pct-launcher-actions .btn { flex:1 1 100%; }
						.pct-search-row { flex-direction:column; }
						.pct-item-card { grid-template-columns:1fr; }
						.pct-item-code, .pct-recent-name { font-size:14px; }
						.pct-item-name { font-size:12px; white-space:normal; }
					}
				</style>
			`);
		}

		this.$homeView = this.wrapper.find(".pct-home-view");
		this.$editorView = this.wrapper.find(".pct-editor-view");
	}

	bindPageActions() {
		this.wrapper.on("click", ".pct-go-home", () => this.goHome());
		this.wrapper.on("click", ".pct-new-carton", () => this.startNewCarton());
		this.wrapper.on("click", ".pct-open-form", () => this.openStandardForm());
		this.wrapper.on("click", ".pct-add-item", () => this.openAddItemDialog());
		this.wrapper.on("click", ".pct-clear-items", () => this.clearItems());
		this.wrapper.on("click", ".pct-save-draft", () => this.saveDoc());
		this.wrapper.on("click", ".pct-save-print", async () => {
			await this.saveDoc();
			this.printDoc();
		});
		this.wrapper.on("click", ".pct-print", () => this.printDoc());
		this.wrapper.on("click", ".pct-qty-btn", (e) => this.adjustQty(e));
		this.wrapper.on("click", ".pct-remove-item", (e) => this.removeItem(e));
		this.wrapper.on("click", ".pct-open-existing", () => this.openExistingDialog());
		this.wrapper.on("click", ".pct-recent-card", (e) => this.openRecentCarton(e));
		this.wrapper.on("click", ".pct-search-cartons", () => this.searchRecentCartons());
		this.wrapper.on("keydown", ".pct-search-input", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				this.searchRecentCartons();
			}
		});
	}

	async refreshView() {
		const token = this.routeToken;
		if (!token) {
			this.state.mode = "home";
			await this.loadHome();
			return;
		}

		if (token === "new") {
			this.state.mode = "new";
			await this.loadDoc();
			return;
		}

		this.state.mode = "edit";
		await this.loadDoc(token);
	}

	async loadHome(searchText = "") {
		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.list_touch_cartons",
			args: { search_text: searchText || null, limit: 12 },
			freeze: true,
			freeze_message: __("Loading cartons..."),
		});

		this.state.recentCartons = response.message || [];
		this.renderHome();
	}

	renderHome() {
		this.page.set_title(__("Packed Carton Touch"));
		this.$editorView.addClass("is-hidden").empty();
		this.$homeView.removeClass("is-hidden").html(`
			<div class="pct-home-shell">
				<div class="pct-side-stack">
					<section class="pct-card">
						<div class="pct-card-title">${__("Operator Console")}</div>
						<h2 class="pct-launcher-title">${__("Start Or Resume")}</h2>
						<div class="pct-launcher-copy">${__("Create a carton or continue an existing one.")}</div>
						<div class="pct-launcher-actions">
							<button class="btn btn-primary btn-lg pct-new-carton">${__("New Carton")}</button>
							<button class="btn btn-default btn-lg pct-open-existing">${__("Resume Carton")}</button>
						</div>
					</section>
					<section class="pct-card">
						<div class="pct-card-title">${__("Quick Search")}</div>
						<div class="pct-search-row">
							<input class="form-control pct-search-input" type="text" placeholder="${__("Search carton number")}" />
							<button class="btn btn-default pct-search-cartons">${__("Search")}</button>
						</div>
						<div class="pct-launcher-copy">${__("Recent cartons are listed on the right.")}</div>
					</section>
				</div>
				<section class="pct-card pct-main-panel">
					<div class="pct-card-title">${__("Recent Cartons")}</div>
					<div class="pct-recent-list"></div>
				</section>
			</div>
		`);

		this.renderRecentCartons();
	}

	renderRecentCartons() {
		const $list = this.wrapper.find(".pct-recent-list");
		if (!this.state.recentCartons.length) {
			$list.html(`<div class="pct-home-empty">${__("No cartons found. Tap 'New Carton' to begin the first one.")}</div>`);
			return;
		}

		$list.html(
			this.state.recentCartons.map((carton) => `
				<div class="pct-recent-card" data-name="${frappe.utils.escape_html(carton.name)}">
					<div class="pct-recent-top">
						<div class="pct-recent-name">${frappe.utils.escape_html(carton.name)}</div>
						<div class="pct-pill">${frappe.utils.escape_html(carton.status || __("Available"))}</div>
					</div>
					<div class="pct-recent-meta">
						<div><strong>${__("Box Type")}:</strong> ${frappe.utils.escape_html(carton.box_type || "-")}</div>
						<div><strong>${__("Packed Date")}:</strong> ${frappe.datetime.str_to_user(carton.packed_date || "") || "-"}</div>
						<div><strong>${__("Warehouse")}:</strong> ${frappe.utils.escape_html(carton.warehouse || "-")}</div>
						<div><strong>${__("Gross Weight")}:</strong> ${flt(carton.gross_weight_kg).toFixed(3)} kg</div>
					</div>
				</div>
			`).join("")
		);
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
		this.renderControls();
		this.render();
	}

	renderEditor() {
		this.page.set_title(this.state.mode === "edit" ? __("Edit Packed Carton") : __("New Packed Carton"));
		this.$homeView.addClass("is-hidden").empty();
		this.$editorView.removeClass("is-hidden").html(`
			<div class="pct-editor-shell">
				<div class="pct-side-stack">
					<section class="pct-card pct-card--form">
						<div class="pct-card-title">${__("Carton")}</div>
						<div class="pct-fields">
							<div class="pct-field" data-field="name"></div>
							<div class="pct-field" data-field="box_type"></div>
							<div class="pct-field" data-field="packed_date"></div>
							<div class="pct-field" data-field="warehouse"></div>
							<div class="pct-field" data-field="packed_by"></div>
							<div class="pct-field" data-field="status"></div>
						</div>
					</section>

					<section class="pct-card pct-card--summary">
						<div class="pct-card-title">${__("Totals")}</div>
						<div class="pct-summary-grid">
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Lines")}</div>
								<div class="pct-summary-value" data-total="lines">0</div>
							</div>
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Total Qty")}</div>
								<div class="pct-summary-value" data-total="pieces">0</div>
							</div>
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Net Weight")}</div>
								<div class="pct-summary-value" data-total="net_weight_kg">0.000 kg</div>
							</div>
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Gross Weight")}</div>
								<div class="pct-summary-value" data-total="gross_weight_kg">0.000 kg</div>
							</div>
						</div>
						<div class="pct-summary-meta">
							<div><strong>${__("Dimensions")}:</strong> <span data-meta="dimensions">-</span></div>
							<div><strong>${__("Empty Box")}:</strong> <span data-meta="empty_weight_g">0 g</span></div>
						</div>
					</section>

					<section class="pct-card pct-card--actions">
						<div class="pct-card-title">${__("Actions")}</div>
						<div class="pct-action-row">
							<button class="btn btn-primary btn-lg pct-add-item">${__("+ Add Item")}</button>
							<button class="btn btn-default btn-lg pct-clear-items">${__("Clear")}</button>
							<button class="btn btn-default btn-lg pct-print">${__("Print")}</button>
						</div>
					</section>
				</div>

				<section class="pct-card pct-main-panel pct-items-panel">
					<div class="pct-card-title">${__("Items In Carton")}</div>
					<div class="pct-items-list"></div>
					<div class="pct-empty-state">${__("No items added yet. Tap '+ Add Item' to begin.")}</div>
					<div class="pct-footer-actions">
						<button class="btn btn-default btn-lg pct-save-draft">${__("Save")}</button>
						<button class="btn btn-primary btn-lg pct-save-print">${__("Save & Print")}</button>
					</div>
				</section>
			</div>
		`);

		this.$itemsList = this.wrapper.find(".pct-items-list");
		this.$emptyState = this.wrapper.find(".pct-empty-state");
	}

	renderControls() {
		const doc = this.state.doc;
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
			const container = this.wrapper.find(`.pct-field[data-field="${df.fieldname}"]`);
			container.empty();
			const control = frappe.ui.form.make_control({
				parent: container,
				df: {
					...df,
					change: () => this.onFieldChange(df.fieldname),
				},
				render_input: true,
			});
			control.set_value(doc[df.fieldname] || "");
			if (df.read_only) {
				control.df.read_only = 1;
				control.refresh();
			}
			this.controls[df.fieldname] = control;
		});
	}

	onFieldChange(fieldname) {
		if (!this.state.doc) return;
		this.state.doc[fieldname] = this.controls[fieldname].get_value();

		if (fieldname === "box_type") {
			if (!this.state.doc.box_type) {
				this.state.doc.dimensions = "";
				this.state.doc.empty_weight_g = 0;
				this.renderSummary();
				return;
			}

			frappe.db.get_doc("Carton Type", this.state.doc.box_type).then((doc) => {
				this.state.doc.dimensions = `${doc.length_in} × ${doc.width_in} × ${doc.height_in} in`;
				this.state.doc.empty_weight_g = doc.empty_weight_g || 0;
				this.renderSummary();
			});
		}
	}

	computeTotals() {
		const net = this.state.items.reduce((sum, item) => sum + (flt(item.qty) * flt(item.item_weight_kg)), 0);
		const pieces = this.state.items.reduce((sum, item) => sum + flt(item.qty), 0);
		const emptyWeight = flt(this.state.doc.empty_weight_g || 0) / 1000;
		this.state.totals = {
			lines: this.state.items.length,
			pieces,
			net_weight_kg: parseFloat(net.toFixed(3)),
			gross_weight_kg: parseFloat((net + emptyWeight).toFixed(3)),
		};
		this.state.doc.net_weight_kg = this.state.totals.net_weight_kg;
		this.state.doc.gross_weight_kg = this.state.totals.gross_weight_kg;
	}

	render() {
		this.computeTotals();
		this.renderItems();
		this.renderSummary();
	}

	renderSummary() {
		this.computeTotals();
		const totals = this.state.totals;
		this.wrapper.find('[data-total="lines"]').text(totals.lines);
		this.wrapper.find('[data-total="pieces"]').text(totals.pieces);
		this.wrapper.find('[data-total="net_weight_kg"]').text(`${totals.net_weight_kg.toFixed(3)} kg`);
		this.wrapper.find('[data-total="gross_weight_kg"]').text(`${totals.gross_weight_kg.toFixed(3)} kg`);
		this.wrapper.find('[data-meta="dimensions"]').text(this.state.doc.dimensions || "-");
		this.wrapper.find('[data-meta="empty_weight_g"]').text(`${flt(this.state.doc.empty_weight_g || 0).toFixed(0)} g`);
		this.controls?.name?.set_value(this.state.doc.name || __("New Carton"));
		this.controls?.status?.set_value(this.state.doc.status || __("Available"));
	}

	renderItems() {
		if (!this.state.items.length) {
			this.$itemsList.empty();
			this.$emptyState.addClass("is-visible");
			return;
		}

		this.$emptyState.removeClass("is-visible");
		this.$itemsList.html(
			this.state.items.map((item, index) => `
				<div class="pct-item-card" data-index="${index}">
					<div class="pct-item-main">
						<div class="pct-item-code">${frappe.utils.escape_html(item.item_code)}</div>
						<div class="pct-item-name">${frappe.utils.escape_html(item.item_name || "")}</div>
					</div>
					<div class="pct-item-meta">
						<div>${__("UOM")}: ${frappe.utils.escape_html(item.uom || "")}</div>
						<div>${__("Wt")}: ${flt(item.item_weight_kg).toFixed(3)} kg/${__("unit")}</div>
					</div>
					<div class="pct-item-actions">
						<div class="pct-qty-controls">
							<button class="pct-qty-btn" data-direction="-1" data-index="${index}">-</button>
							<div class="pct-qty-display">${flt(item.qty)}</div>
							<button class="pct-qty-btn" data-direction="1" data-index="${index}">+</button>
						</div>
						<button class="btn btn-danger pct-remove-item" data-index="${index}">${__("Remove Item")}</button>
					</div>
				</div>
			`).join("")
		);
	}

	async openAddItemDialog() {
		const d = new frappe.ui.Dialog({
			title: __("Add Item"),
			fields: [
				{
					fieldname: "item_code",
					fieldtype: "Link",
					options: "Item",
					label: __("Item"),
					reqd: 1,
				},
				{
					fieldname: "qty",
					fieldtype: "Float",
					label: __("Qty"),
					reqd: 1,
					default: 1,
				},
			],
			primary_action_label: __("Add"),
			primary_action: async (values) => {
				if (!values.item_code || !(values.qty > 0)) {
					frappe.show_alert({ indicator: "orange", message: __("Please choose an item and enter a valid quantity.") });
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

				this.render();
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
		this.render();
	}

	removeItem(event) {
		const index = cint($(event.currentTarget).data("index"));
		this.state.items.splice(index, 1);
		this.render();
	}

	clearItems() {
		if (!this.state.items.length) return;
		this.state.items = [];
		this.render();
	}

	buildPayload() {
		return {
			name: this.state.doc.name || null,
			box_type: this.controls.box_type.get_value(),
			packed_date: this.controls.packed_date.get_value(),
			warehouse: this.controls.warehouse.get_value(),
			packed_by: this.controls.packed_by.get_value(),
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
		this.state.mode = "edit";
		if (this.state.doc.name && this.routeToken !== this.state.doc.name) {
			frappe.set_route("packed_carton_touch", this.state.doc.name);
		}
		frappe.show_alert({ indicator: "green", message: __(`${this.state.doc.name} saved`) });
		this.renderControls();
		this.render();
		return this.state.doc;
	}

	goHome() {
		frappe.set_route("packed_carton_touch");
	}

	startNewCarton() {
		frappe.set_route("packed_carton_touch", "new");
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
				frappe.set_route("packed_carton_touch", values.carton_name);
				d.hide();
			},
		});
		d.show();
	}

	openRecentCarton(event) {
		const name = $(event.currentTarget).data("name");
		if (!name) return;
		frappe.set_route("packed_carton_touch", name);
	}

	searchRecentCartons() {
		const searchText = (this.wrapper.find(".pct-search-input").val() || "").trim();
		this.loadHome(searchText);
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
