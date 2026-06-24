frappe.provide("snrg_supplychain.packing_station");

frappe.pages["packing_station"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Carton Packing"),
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
			doc: null,
			items: [],
			recentCartons: [],
			selectedItemCode: "",
			selectedItemData: null,
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
			<div class="ps2-app">
				<div class="ps2-topbar">
						<div>
						<div class="ps2-badge">${__("Carton Packing")}</div>
						<div class="ps2-title">${__("Packing Station")}</div>
					</div>
					<div class="ps2-topbar-actions">
						<button class="btn btn-default ps2-home-btn">${__("Home")}</button>
						<button class="btn btn-primary ps2-new-btn">${__("New Carton")}</button>
					</div>
				</div>
				<div class="ps2-home-view"></div>
				<div class="ps2-editor-view"></div>
			</div>
		`);

		if (!document.getElementById("packing-station-style-v2")) {
			$("head").append(`
				<style id="packing-station-style-v2">
					.ps2-app {
						min-height: calc(100vh - 92px);
						height: calc(100vh - 92px);
						overflow: hidden;
						background: #eef2f6;
						color: #16202a;
						padding: 8px;
					}
					.ps2-topbar {
						display: flex;
						justify-content: space-between;
						align-items: center;
						gap: 12px;
						background: #111b27;
						color: #fff;
						border-radius: 12px;
						padding: 10px 12px;
						margin-bottom: 8px;
					}
					.ps2-badge {
						font-size: 10px;
						text-transform: uppercase;
						letter-spacing: 0.12em;
						color: #8fa2bb;
						font-weight: 700;
					}
					.ps2-title {
						font-size: 20px;
						font-weight: 900;
						line-height: 1.1;
						margin-top: 2px;
					}
					.ps2-topbar-actions,
					.ps2-home-actions,
					.ps2-search-row,
					.ps2-entry-actions,
					.ps2-footer-actions {
						display: flex;
						gap: 8px;
						flex-wrap: wrap;
					}
					.ps2-topbar-actions .btn,
					.ps2-home-actions .btn,
					.ps2-entry-actions .btn,
					.ps2-footer-actions .btn,
					.ps2-search-row .btn {
						min-height: 38px;
						border-radius: 10px;
						font-size: 13px;
						font-weight: 800;
						padding: 0 12px;
					}
					.ps2-home-btn {
						background: #223244;
						color: #fff;
						border-color: #223244;
					}
					.ps2-home-layout,
					.ps2-editor-layout {
						display: grid;
						gap: 8px;
						height: calc(100vh - 148px);
						min-height: 0;
					}
					.ps2-home-layout {
						grid-template-columns: 320px minmax(0, 1fr);
					}
					.ps2-editor-layout {
						grid-template-rows: auto auto 1fr auto;
					}
					.ps2-card,
					.ps2-panel,
					.ps2-strip {
						background: #fff;
						border: 1px solid #d8e1eb;
						border-radius: 12px;
						padding: 10px;
					}
					.ps2-card-title {
						font-size: 10px;
						text-transform: uppercase;
						letter-spacing: 0.1em;
						font-weight: 800;
						color: #67788a;
						margin-bottom: 8px;
					}
					.ps2-home-stack {
						display: grid;
						gap: 8px;
						align-content: start;
					}
					.ps2-home-title {
						font-size: 18px;
						font-weight: 900;
						margin-bottom: 4px;
					}
					.ps2-home-copy,
					.ps2-subtle,
					.ps2-item-preview,
					.ps2-list-subtitle {
						font-size: 12px;
						color: #66788a;
					}
					.ps2-tile-grid {
						display: grid;
						grid-template-columns: repeat(2, minmax(0, 1fr));
						gap: 8px;
					}
					.ps2-tile {
						border: none;
						border-radius: 14px;
						min-height: 118px;
						padding: 14px;
						color: #fff;
						text-align: left;
						display: flex;
						flex-direction: column;
						justify-content: space-between;
					}
					.ps2-tile-title {
						font-size: 16px;
						font-weight: 900;
						line-height: 1.1;
					}
					.ps2-tile-copy {
						font-size: 11px;
						line-height: 1.35;
						opacity: 0.92;
					}
					.ps2-tile--blue { background: #0f6cbd; }
					.ps2-tile--teal { background: #0a9396; }
					.ps2-tile--violet { background: #7b2cbf; }
					.ps2-tile--orange { background: #ee6c4d; }
					.ps2-search-row input,
					.ps2-search-input {
						min-height: 38px;
						border-radius: 10px;
						font-size: 14px;
						font-weight: 700;
						background: #f7f9fb;
					}
					.ps2-recent-panel,
					.ps2-list-panel {
						display: grid;
						grid-template-rows: auto auto 1fr;
						min-height: 0;
					}
					.ps2-recent-list,
					.ps2-items-body {
						overflow: auto;
						display: grid;
						gap: 6px;
						align-content: start;
					}
					.ps2-recent-card {
						border: 1px solid #d8e1eb;
						border-radius: 10px;
						background: #fff;
						padding: 10px;
						cursor: pointer;
					}
					.ps2-recent-card:hover { background: #f7f9fb; }
					.ps2-recent-top {
						display: flex;
						justify-content: space-between;
						gap: 8px;
						align-items: flex-start;
					}
					.ps2-recent-name { font-size: 14px; font-weight: 900; }
					.ps2-recent-pill {
						min-height: 22px;
						padding: 0 8px;
						border-radius: 999px;
						background: #ebf5ee;
						color: #0f6a34;
						font-size: 10px;
						font-weight: 800;
						display: inline-flex;
						align-items: center;
					}
					.ps2-recent-meta { margin-top: 4px; display: grid; gap: 2px; font-size: 11px; color: #66788a; }
					.ps2-empty {
						border: 1px dashed #b8c5d3;
						border-radius: 10px;
						background: #f7f9fb;
						padding: 18px;
						text-align: center;
						font-size: 13px;
						font-weight: 700;
						color: #66788a;
					}
					.ps2-setup-strip {
						display: grid;
						grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 220px;
						gap: 8px;
						align-items: end;
					}
					.ps2-field .control-label {
						font-size: 10px;
						font-weight: 700;
						color: #5b6b7c;
						margin-bottom: 4px;
					}
					.ps2-field .control-input-wrapper input,
					.ps2-field .control-input-wrapper .control-value,
					.ps2-field .control-input-wrapper .awesomplete input,
					.ps2-field .control-input-wrapper select {
						min-height: 40px;
						border-radius: 10px;
						font-size: 15px;
						font-weight: 700;
						background: #f7f9fb;
						border-color: #d8e1eb;
					}
					.ps2-total-boxes {
						display: grid;
						grid-template-columns: repeat(3, minmax(0, 1fr));
						gap: 6px;
					}
					.ps2-total-box {
						border: 1px solid #d8e1eb;
						border-radius: 10px;
						background: #f7f9fb;
						padding: 8px;
					}
					.ps2-total-label {
						font-size: 10px;
						text-transform: uppercase;
						letter-spacing: 0.08em;
						color: #67788a;
						font-weight: 700;
					}
					.ps2-total-value {
						font-size: 16px;
						font-weight: 900;
						margin-top: 2px;
					}
					.ps2-entry-layout {
						min-height: 0;
					}
					.ps2-entry-panel {
						background: #fff;
						border: 1px solid #d8e1eb;
						border-radius: 12px;
						padding: 10px;
					}
					.ps2-entry-panel { display: grid; grid-template-rows: auto auto auto; gap: 8px; }
					.ps2-item-select { display: grid; gap: 8px; }
					.ps2-qty-box {
						border: 1px solid #d8e1eb;
						border-radius: 12px;
						background: #f7f9fb;
						padding: 12px;
					}
					.ps2-qty-label {
						font-size: 10px;
						text-transform: uppercase;
						letter-spacing: 0.08em;
						color: #67788a;
						font-weight: 700;
					}
					.ps2-qty-input {
						width: 100%;
						margin-top: 6px;
						min-height: 72px;
						border: 1px solid #d8e1eb;
						border-radius: 12px;
						background: #fff;
						padding: 12px 16px;
						font-size: 32px;
						font-weight: 900;
						line-height: 1;
						color: #16202a;
					}
					.ps2-qty-input:focus {
						outline: none;
						border-color: #7aa7d9;
						box-shadow: 0 0 0 3px rgba(17, 115, 212, 0.12);
					}
					.ps2-list-panel { min-height: 0; }
					.ps2-list-header,
					.ps2-item-row {
						display: grid;
						grid-template-columns: minmax(0, 2fr) 100px 110px 96px;
						gap: 8px;
						align-items: center;
						padding: 8px 10px;
					}
					.ps2-list-header {
						font-size: 10px;
						text-transform: uppercase;
						letter-spacing: 0.08em;
						font-weight: 800;
						color: #67788a;
						background: #f7f9fb;
						border: 1px solid #d8e1eb;
						border-radius: 10px;
						margin-bottom: 6px;
					}
					.ps2-item-row {
						background: #fff;
						border: 1px solid #d8e1eb;
						border-radius: 10px;
					}
					.ps2-item-main { min-width: 0; }
					.ps2-item-code { font-size: 14px; font-weight: 900; }
					.ps2-item-name { font-size: 12px; color: #66788a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
					.ps2-item-qty,
					.ps2-item-uom,
					.ps2-item-weight { font-size: 13px; font-weight: 700; }
					.ps2-remove-btn {
						min-height: 34px;
						border-radius: 8px;
						font-size: 12px;
						font-weight: 800;
					}
					.ps2-editor-view.is-hidden,
					.ps2-home-view.is-hidden { display: none; }
					@media (max-width: 1100px) {
						.ps2-app { height: auto; overflow: auto; }
						.ps2-home-layout { height: auto; grid-template-columns: 1fr; }
						.ps2-editor-layout { height: auto; }
						.ps2-setup-strip { grid-template-columns: 1fr; }
					}
					@media (max-width: 800px) {
						.ps2-topbar { display: grid; align-items: start; }
						.ps2-tile-grid { grid-template-columns: 1fr; }
						.ps2-list-header,
						.ps2-item-row { grid-template-columns: 1fr; }
						.ps2-topbar-actions .btn,
						.ps2-home-actions .btn,
						.ps2-entry-actions .btn,
						.ps2-footer-actions .btn,
						.ps2-search-row .btn { flex: 1 1 100%; }
						.ps2-search-row { flex-direction: column; }
					}
				</style>
			`);
		}

		this.$homeView = this.wrapper.find(".ps2-home-view");
		this.$editorView = this.wrapper.find(".ps2-editor-view");
	}

	bindActions() {
		this.wrapper.on("click", ".ps2-home-btn", () => this.goHome());
		this.wrapper.on("click", ".ps2-new-btn", () => this.startNew());
		this.wrapper.on("click", ".ps2-resume-btn", () => this.openExistingDialog());
		this.wrapper.on("click", ".ps2-recent-card", (e) => this.openRecent($(e.currentTarget).data("name")));
		this.wrapper.on("click", ".ps2-search-btn", () => this.searchRecent());
		this.wrapper.on("keydown", ".ps2-search-input", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				this.searchRecent();
			}
		});
		this.wrapper.on("click", ".ps2-add-item", () => this.addCurrentItem());
		this.wrapper.on("click", ".ps2-clear-carton", () => this.clearItems());
		this.wrapper.on("click", ".ps2-save", () => this.saveDoc());
		this.wrapper.on("click", ".ps2-save-print", async () => {
			await this.saveDoc();
			this.printDoc();
		});
		this.wrapper.on("click", ".ps2-remove-btn", (e) => this.removeItem($(e.currentTarget).data("index")));
	}

	async refreshView() {
		const token = this.routeToken;
		if (!token) {
			this.state.mode = "home";
			await this.loadHome();
			return;
		}

		this.state.mode = "editor";
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
		this.page.set_title(__("Carton Packing"));
		this.$editorView.addClass("is-hidden").empty();
		this.$homeView.removeClass("is-hidden").html(`
			<div class="ps2-home-layout">
				<div class="ps2-home-stack">
					<div class="ps2-card">
						<div class="ps2-home-title">${__("Start Work")}</div>
						<div class="ps2-home-copy">${__("Use the station like a handheld device. Tap a tile to begin.")}</div>
						<div class="ps2-tile-grid">
							<button class="ps2-tile ps2-tile--blue ps2-new-btn">
								<div class="ps2-tile-title">${__("New Carton")}</div>
								<div class="ps2-tile-copy">${__("Start a fresh packing workflow")}</div>
							</button>
							<button class="ps2-tile ps2-tile--teal ps2-resume-btn">
								<div class="ps2-tile-title">${__("Resume")}</div>
								<div class="ps2-tile-copy">${__("Open an existing carton and continue work")}</div>
							</button>
							<button class="ps2-tile ps2-tile--violet ps2-search-btn">
								<div class="ps2-tile-title">${__("Search")}</div>
								<div class="ps2-tile-copy">${__("Find carton by number from the search box below")}</div>
							</button>
						</div>
					</div>
					<div class="ps2-card">
						<div class="ps2-home-title">${__("Search")}</div>
						<div class="ps2-search-row">
							<input class="form-control ps2-search-input" type="text" placeholder="${__("Search carton number")}" />
							<button class="btn btn-default ps2-search-btn">${__("Search")}</button>
						</div>
					</div>
				</div>
				<div class="ps2-card ps2-recent-panel">
					<div class="ps2-card-title">${__("Recent Cartons")}</div>
					<div class="ps2-list-subtitle">${__("Tap a carton to reopen it in the station.")}</div>
					<div class="ps2-recent-list"></div>
				</div>
			</div>
		`);

		const $list = this.wrapper.find(".ps2-recent-list");
		if (!this.state.recentCartons.length) {
			$list.html(`<div class="ps2-empty">${__("No cartons yet. Start a new carton to begin packing.")}</div>`);
			return;
		}

		$list.html(this.state.recentCartons.map((carton) => `
			<div class="ps2-recent-card" data-name="${frappe.utils.escape_html(carton.name)}">
				<div class="ps2-recent-top">
					<div class="ps2-recent-name">${frappe.utils.escape_html(carton.name)}</div>
					<div class="ps2-recent-pill">${frappe.utils.escape_html(carton.status || __("Available"))}</div>
				</div>
				<div class="ps2-recent-meta">
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
		this.state.selectedItemCode = "";
		this.state.selectedItemData = null;
		this.renderEditor();
		this.renderControls();
		this.renderEditorState();
	}

	renderEditor() {
		this.page.set_title(this.state.doc?.name || __("New Carton"));
		this.$homeView.addClass("is-hidden").empty();
		this.$editorView.removeClass("is-hidden").html(`
			<div class="ps2-editor-layout">
				<div class="ps2-strip ps2-setup-strip">
					<div class="ps2-field" data-field="box_type"></div>
					<div class="ps2-field" data-field="warehouse"></div>
					<div class="ps2-total-boxes">
						<div class="ps2-total-box"><div class="ps2-total-label">${__("Lines")}</div><div class="ps2-total-value" data-total="lines">0</div></div>
						<div class="ps2-total-box"><div class="ps2-total-label">${__("Qty")}</div><div class="ps2-total-value" data-total="pieces">0</div></div>
						<div class="ps2-total-box"><div class="ps2-total-label">${__("Gross")}</div><div class="ps2-total-value" data-total="gross">0</div></div>
					</div>
				</div>
				<div class="ps2-entry-layout">
					<div class="ps2-entry-panel">
						<div class="ps2-card-title">${__("Item Entry")}</div>
						<div class="ps2-item-select">
							<div class="ps2-field" data-field="item_code"></div>
							<div class="ps2-item-preview">${__("Select an item to preview it here.")}</div>
						</div>
						<div class="ps2-qty-box">
							<div class="ps2-qty-label">${__("Quantity")}</div>
							<input
								type="number"
								inputmode="numeric"
								min="0"
								step="1"
								class="ps2-qty-input"
								placeholder="${__("Enter quantity")}"
							/>
						</div>
						<div class="ps2-entry-actions">
							<button class="btn btn-primary ps2-add-item">${__("Add Item")}</button>
							<button class="btn btn-default ps2-clear-carton">${__("Clear Carton")}</button>
						</div>
					</div>
				</div>
				<div class="ps2-panel ps2-list-panel">
					<div class="ps2-card-title">${__("Current Items")}</div>
					<div class="ps2-list-subtitle">${__("Items already added to this carton.")}</div>
					<div class="ps2-list-header">
						<div>${__("Item")}</div>
						<div>${__("Qty")}</div>
						<div>${__("UOM")}</div>
						<div>${__("Action")}</div>
					</div>
					<div class="ps2-items-body"></div>
				</div>
				<div class="ps2-footer-actions">
					<button class="btn btn-default ps2-save">${__("Save")}</button>
					<button class="btn btn-primary ps2-save-print">${__("Save & Print")}</button>
				</div>
			</div>
		`);
	}

	renderControls() {
		const fields = [
			{ fieldname: "box_type", label: __("Box Type"), fieldtype: "Link", options: "Carton Type", reqd: 1 },
			{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1 },
			{ fieldname: "item_code", label: __("Select Item"), fieldtype: "Link", options: "Item", reqd: 0 },
		];

		this.controls = {};
		fields.forEach((df) => {
			const container = this.wrapper.find(`.ps2-field[data-field="${df.fieldname}"]`);
			const control = frappe.ui.form.make_control({
				parent: container,
				df: {
					...df,
					change: () => this.onFieldChange(df.fieldname),
				},
				render_input: true,
			});
			control.set_value(this.getFieldValue(df.fieldname));
			this.controls[df.fieldname] = control;
		});
	}

	getFieldValue(fieldname) {
		if (fieldname === "item_code") return this.state.selectedItemCode || "";
		return this.state.doc?.[fieldname] || "";
	}

	onFieldChange(fieldname) {
		if (fieldname === "item_code") {
			this.state.selectedItemCode = this.controls.item_code.get_value();
			this.loadSelectedItemPreview();
			return;
		}

		this.syncDocFromControls();
		if (fieldname === "box_type") {
			if (!this.state.doc.box_type) {
				this.state.doc.dimensions = "";
				this.state.doc.empty_weight_g = 0;
				this.renderTotals();
				return;
			}
			frappe.db.get_doc("Carton Type", this.state.doc.box_type).then((doc) => {
				this.state.doc.dimensions = `${doc.length_in} x ${doc.width_in} x ${doc.height_in} in`;
				this.state.doc.empty_weight_g = doc.empty_weight_g || 0;
				this.renderTotals();
			});
		}
	}

	async loadSelectedItemPreview() {
		const itemCode = this.state.selectedItemCode;
		if (!itemCode) {
			this.state.selectedItemData = null;
			this.renderSelectedItemPreview();
			return;
		}

		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.get_touch_item",
			args: { item_code: itemCode },
		});
		this.state.selectedItemData = response.message;
		this.renderSelectedItemPreview();
	}

	renderSelectedItemPreview() {
		const $preview = this.wrapper.find(".ps2-item-preview");
		if (!$preview.length) return;
		if (!this.state.selectedItemData) {
			$preview.text(__("Select an item to preview it here."));
			return;
		}
		$preview.text(`${this.state.selectedItemData.item_name} | ${this.state.selectedItemData.uom} | ${flt(this.state.selectedItemData.item_weight_kg).toFixed(3)} kg/${__("unit")}`);
	}

	syncDocFromControls() {
		if (!this.controls || !this.state.doc) return;
		this.state.doc.box_type = this.controls.box_type.get_value();
		this.state.doc.warehouse = this.controls.warehouse.get_value();
	}

	getQtyValue() {
		return cint(this.wrapper.find(".ps2-qty-input").val() || 0);
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

	renderTotals() {
		this.computeTotals();
		this.wrapper.find('[data-total="lines"]').text(this.state.totals.lines);
		this.wrapper.find('[data-total="pieces"]').text(this.state.totals.pieces);
		this.wrapper.find('[data-total="gross"]').text(this.state.totals.gross_weight_kg.toFixed(3));
	}

	renderItemRows() {
		const $body = this.wrapper.find(".ps2-items-body");
		if (!$body.length) return;
		if (!this.state.items.length) {
			$body.html(`<div class="ps2-empty">${__("No items added yet. Select an item, enter quantity, and tap 'Add Item'.")}</div>`);
			this.renderTotals();
			return;
		}
		$body.html(this.state.items.map((item, index) => `
			<div class="ps2-item-row">
				<div class="ps2-item-main">
					<div class="ps2-item-code">${frappe.utils.escape_html(item.item_code)}</div>
					<div class="ps2-item-name">${frappe.utils.escape_html(item.item_name || "")}</div>
				</div>
				<div class="ps2-item-qty">${flt(item.qty)}</div>
				<div class="ps2-item-uom">${frappe.utils.escape_html(item.uom || "")}</div>
				<div><button class="btn btn-default ps2-remove-btn" data-index="${index}">${__("Remove")}</button></div>
			</div>
		`).join(""));
		this.renderTotals();
	}

	renderEditorState() {
		this.renderSelectedItemPreview();
		this.renderItemRows();
	}

	async addCurrentItem() {
		this.syncDocFromControls();
		if (!this.state.doc.box_type || !this.state.doc.warehouse) {
			frappe.show_alert({ indicator: "orange", message: __("Select Box Type and Warehouse first.") });
			return;
		}
		if (!this.state.selectedItemCode) {
			frappe.show_alert({ indicator: "orange", message: __("Select an item first.") });
			return;
		}
		const qty = this.getQtyValue();
		if (!(qty > 0)) {
			frappe.show_alert({ indicator: "orange", message: __("Enter a valid quantity.") });
			return;
		}

		let itemData = this.state.selectedItemData;
		if (!itemData || itemData.item_code !== this.state.selectedItemCode) {
			const response = await frappe.call({
				method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.get_touch_item",
				args: { item_code: this.state.selectedItemCode },
			});
			itemData = response.message;
		}

		const existing = this.state.items.find((row) => row.item_code === itemData.item_code);
		if (existing) {
			existing.qty = flt(existing.qty) + qty;
		} else {
			this.state.items.push({
				item_code: itemData.item_code,
				item_name: itemData.item_name,
				uom: itemData.uom,
				item_weight_kg: itemData.item_weight_kg,
				qty,
			});
		}

		this.state.selectedItemCode = "";
		this.state.selectedItemData = null;
		if (this.controls.item_code) {
			this.controls.item_code.set_value("");
		}
		this.wrapper.find(".ps2-qty-input").val("");
		this.renderEditorState();
		frappe.show_alert({ indicator: "green", message: __("Item added to carton") });
	}

	removeItem(index) {
		this.state.items.splice(cint(index), 1);
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
		this.renderEditor();
		this.renderControls();
		this.renderEditorState();
		frappe.show_alert({ indicator: "green", message: __(`${this.state.doc.name} saved`) });
		return this.state.doc;
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
		const searchText = (this.wrapper.find(".ps2-search-input").val() || "").trim();
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

	openStandardForm() {
		if (this.state.doc?.name) {
			frappe.set_route("packing_station", this.state.doc.name);
			return;
		}
		frappe.set_route("packing_station", "new");
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
