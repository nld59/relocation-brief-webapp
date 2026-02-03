/*
 * ATTENTION: An "eval-source-map" devtool has been used.
 * This devtool is neither made for production nor for readable output files.
 * It uses "eval()" calls to create a separate source file with attached SourceMaps in the browser devtools.
 * If you are trying to read the output file, select a different devtool (https://webpack.js.org/configuration/devtool/)
 * or disable the default devtool with "devtool: false".
 * If you are looking for production-ready output files, see mode: "production" (https://webpack.js.org/configuration/mode/).
 */
(() => {
var exports = {};
exports.id = "pages/_app";
exports.ids = ["pages/_app"];
exports.modules = {

/***/ "./components/quizState.js":
/*!*********************************!*\
  !*** ./components/quizState.js ***!
  \*********************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
eval("__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   QuizProvider: () => (/* binding */ QuizProvider),\n/* harmony export */   resetQuiz: () => (/* binding */ resetQuiz),\n/* harmony export */   useQuiz: () => (/* binding */ useQuiz)\n/* harmony export */ });\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react/jsx-dev-runtime */ \"react/jsx-dev-runtime\");\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__);\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! react */ \"react\");\n/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_1__);\n\n\nconst QuizContext = /*#__PURE__*/ (0,react__WEBPACK_IMPORTED_MODULE_1__.createContext)(null);\nconst DEFAULT = {\n    city: \"\",\n    householdType: \"\",\n    childrenCount: 0,\n    childrenAges: [],\n    mode: \"buy\",\n    bedrooms: \"\",\n    propertyType: \"\",\n    budgetMin: null,\n    budgetMax: null,\n    priorities: [],\n    includeWorkCommute: null,\n    workTransport: \"\",\n    workMinutes: 30,\n    workAddress: \"\",\n    includeSchoolCommute: null,\n    schoolTransport: \"\",\n    schoolMinutes: 20\n};\nfunction load() {\n    if (true) return DEFAULT;\n    try {\n        const raw = window.localStorage.getItem(\"rb_state_v2\");\n        if (!raw) return DEFAULT;\n        return {\n            ...DEFAULT,\n            ...JSON.parse(raw)\n        };\n    } catch  {\n        return DEFAULT;\n    }\n}\nfunction QuizProvider({ children }) {\n    const [state, setState] = (0,react__WEBPACK_IMPORTED_MODULE_1__.useState)(DEFAULT);\n    (0,react__WEBPACK_IMPORTED_MODULE_1__.useEffect)(()=>{\n        setState(load());\n    }, []);\n    (0,react__WEBPACK_IMPORTED_MODULE_1__.useEffect)(()=>{\n        if (true) return;\n        window.localStorage.setItem(\"rb_state_v2\", JSON.stringify(state));\n    }, [\n        state\n    ]);\n    const value = (0,react__WEBPACK_IMPORTED_MODULE_1__.useMemo)(()=>({\n            state,\n            setState\n        }), [\n        state\n    ]);\n    return /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(QuizContext.Provider, {\n        value: value,\n        children: children\n    }, void 0, false, {\n        fileName: \"C:\\\\Users\\\\nlabuzov\\\\Desktop\\\\Nikita\\\\Projects\\\\relocation-ai-assistant\\\\relocation-brief-webapp\\\\frontend\\\\components\\\\quizState.js\",\n        lineNumber: 51,\n        columnNumber: 10\n    }, this);\n}\nfunction useQuiz() {\n    const ctx = (0,react__WEBPACK_IMPORTED_MODULE_1__.useContext)(QuizContext);\n    if (!ctx) throw new Error(\"QuizProvider missing\");\n    return ctx;\n}\nfunction resetQuiz(setState) {\n    setState(DEFAULT);\n    if (false) {}\n}\n//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiLi9jb21wb25lbnRzL3F1aXpTdGF0ZS5qcyIsIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7OztBQUFzRjtBQUV0RixNQUFNTSw0QkFBY0wsb0RBQWFBLENBQUM7QUFFbEMsTUFBTU0sVUFBVTtJQUNkQyxNQUFNO0lBQ05DLGVBQWU7SUFDZkMsZUFBZTtJQUNmQyxjQUFjLEVBQUU7SUFDaEJDLE1BQU07SUFDTkMsVUFBVTtJQUNWQyxjQUFjO0lBQ2RDLFdBQVc7SUFDWEMsV0FBVztJQUNYQyxZQUFZLEVBQUU7SUFFZEMsb0JBQW9CO0lBQ3BCQyxlQUFlO0lBQ2ZDLGFBQWE7SUFDYkMsYUFBYTtJQUViQyxzQkFBc0I7SUFDdEJDLGlCQUFpQjtJQUNqQkMsZUFBZTtBQUNqQjtBQUVBLFNBQVNDO0lBQ1AsSUFBSSxJQUFrQixFQUFhLE9BQU9sQjtJQUMxQyxJQUFJO1FBQ0YsTUFBTW1CLE1BQU1DLE9BQU9DLFlBQVksQ0FBQ0MsT0FBTyxDQUFDO1FBQ3hDLElBQUksQ0FBQ0gsS0FBSyxPQUFPbkI7UUFDakIsT0FBTztZQUFFLEdBQUdBLE9BQU87WUFBRSxHQUFHdUIsS0FBS0MsS0FBSyxDQUFDTCxJQUFJO1FBQUM7SUFDMUMsRUFBRSxPQUFNO1FBQ04sT0FBT25CO0lBQ1Q7QUFDRjtBQUVPLFNBQVN5QixhQUFhLEVBQUVDLFFBQVEsRUFBRTtJQUN2QyxNQUFNLENBQUNDLE9BQU9DLFNBQVMsR0FBRzlCLCtDQUFRQSxDQUFDRTtJQUVuQ0osZ0RBQVNBLENBQUM7UUFDUmdDLFNBQVNWO0lBQ1gsR0FBRyxFQUFFO0lBRUx0QixnREFBU0EsQ0FBQztRQUNSLElBQUksSUFBa0IsRUFBYTtRQUNuQ3dCLE9BQU9DLFlBQVksQ0FBQ1EsT0FBTyxDQUFDLGVBQWVOLEtBQUtPLFNBQVMsQ0FBQ0g7SUFDNUQsR0FBRztRQUFDQTtLQUFNO0lBRVYsTUFBTUksUUFBUWxDLDhDQUFPQSxDQUFDLElBQU87WUFBRThCO1lBQU9DO1FBQVMsSUFBSTtRQUFDRDtLQUFNO0lBQzFELHFCQUFPLDhEQUFDNUIsWUFBWWlDLFFBQVE7UUFBQ0QsT0FBT0E7a0JBQVFMOzs7Ozs7QUFDOUM7QUFFTyxTQUFTTztJQUNkLE1BQU1DLE1BQU12QyxpREFBVUEsQ0FBQ0k7SUFDdkIsSUFBSSxDQUFDbUMsS0FBSyxNQUFNLElBQUlDLE1BQU07SUFDMUIsT0FBT0Q7QUFDVDtBQUVPLFNBQVNFLFVBQVVSLFFBQVE7SUFDaENBLFNBQVM1QjtJQUNULElBQUksS0FBa0IsRUFBYW9CLEVBQStCO0FBQ3BFIiwic291cmNlcyI6WyJ3ZWJwYWNrOi8vcmVsb2NhdGlvbi1icmllZi1mcm9udGVuZC8uL2NvbXBvbmVudHMvcXVpelN0YXRlLmpzPzc1MDciXSwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0IFJlYWN0LCB7IGNyZWF0ZUNvbnRleHQsIHVzZUNvbnRleHQsIHVzZUVmZmVjdCwgdXNlTWVtbywgdXNlU3RhdGUgfSBmcm9tICdyZWFjdCdcblxuY29uc3QgUXVpekNvbnRleHQgPSBjcmVhdGVDb250ZXh0KG51bGwpXG5cbmNvbnN0IERFRkFVTFQgPSB7XG4gIGNpdHk6ICcnLFxuICBob3VzZWhvbGRUeXBlOiAnJywgLy8gc29sbyB8IGNvdXBsZSB8IGZhbWlseVxuICBjaGlsZHJlbkNvdW50OiAwLFxuICBjaGlsZHJlbkFnZXM6IFtdLFxuICBtb2RlOiAnYnV5JywgLy8gYnV5IHwgcmVudFxuICBiZWRyb29tczogJycsIC8vIHN0dWRpb3wxfDJ8M1xuICBwcm9wZXJ0eVR5cGU6ICcnLCAvLyBhcGFydG1lbnR8aG91c2V8bm90X3N1cmVcbiAgYnVkZ2V0TWluOiBudWxsLFxuICBidWRnZXRNYXg6IG51bGwsXG4gIHByaW9yaXRpZXM6IFtdLFxuXG4gIGluY2x1ZGVXb3JrQ29tbXV0ZTogbnVsbCwgLy8gdHJ1ZXxmYWxzZXxudWxsXG4gIHdvcmtUcmFuc3BvcnQ6ICcnLFxuICB3b3JrTWludXRlczogMzAsXG4gIHdvcmtBZGRyZXNzOiAnJyxcblxuICBpbmNsdWRlU2Nob29sQ29tbXV0ZTogbnVsbCxcbiAgc2Nob29sVHJhbnNwb3J0OiAnJyxcbiAgc2Nob29sTWludXRlczogMjBcbn1cblxuZnVuY3Rpb24gbG9hZCgpIHtcbiAgaWYgKHR5cGVvZiB3aW5kb3cgPT09ICd1bmRlZmluZWQnKSByZXR1cm4gREVGQVVMVFxuICB0cnkge1xuICAgIGNvbnN0IHJhdyA9IHdpbmRvdy5sb2NhbFN0b3JhZ2UuZ2V0SXRlbSgncmJfc3RhdGVfdjInKVxuICAgIGlmICghcmF3KSByZXR1cm4gREVGQVVMVFxuICAgIHJldHVybiB7IC4uLkRFRkFVTFQsIC4uLkpTT04ucGFyc2UocmF3KSB9XG4gIH0gY2F0Y2gge1xuICAgIHJldHVybiBERUZBVUxUXG4gIH1cbn1cblxuZXhwb3J0IGZ1bmN0aW9uIFF1aXpQcm92aWRlcih7IGNoaWxkcmVuIH0pIHtcbiAgY29uc3QgW3N0YXRlLCBzZXRTdGF0ZV0gPSB1c2VTdGF0ZShERUZBVUxUKVxuXG4gIHVzZUVmZmVjdCgoKSA9PiB7XG4gICAgc2V0U3RhdGUobG9hZCgpKVxuICB9LCBbXSlcblxuICB1c2VFZmZlY3QoKCkgPT4ge1xuICAgIGlmICh0eXBlb2Ygd2luZG93ID09PSAndW5kZWZpbmVkJykgcmV0dXJuXG4gICAgd2luZG93LmxvY2FsU3RvcmFnZS5zZXRJdGVtKCdyYl9zdGF0ZV92MicsIEpTT04uc3RyaW5naWZ5KHN0YXRlKSlcbiAgfSwgW3N0YXRlXSlcblxuICBjb25zdCB2YWx1ZSA9IHVzZU1lbW8oKCkgPT4gKHsgc3RhdGUsIHNldFN0YXRlIH0pLCBbc3RhdGVdKVxuICByZXR1cm4gPFF1aXpDb250ZXh0LlByb3ZpZGVyIHZhbHVlPXt2YWx1ZX0+e2NoaWxkcmVufTwvUXVpekNvbnRleHQuUHJvdmlkZXI+XG59XG5cbmV4cG9ydCBmdW5jdGlvbiB1c2VRdWl6KCkge1xuICBjb25zdCBjdHggPSB1c2VDb250ZXh0KFF1aXpDb250ZXh0KVxuICBpZiAoIWN0eCkgdGhyb3cgbmV3IEVycm9yKCdRdWl6UHJvdmlkZXIgbWlzc2luZycpXG4gIHJldHVybiBjdHhcbn1cblxuZXhwb3J0IGZ1bmN0aW9uIHJlc2V0UXVpeihzZXRTdGF0ZSkge1xuICBzZXRTdGF0ZShERUZBVUxUKVxuICBpZiAodHlwZW9mIHdpbmRvdyAhPT0gJ3VuZGVmaW5lZCcpIHdpbmRvdy5sb2NhbFN0b3JhZ2UucmVtb3ZlSXRlbSgncmJfc3RhdGVfdjInKVxufVxuIl0sIm5hbWVzIjpbIlJlYWN0IiwiY3JlYXRlQ29udGV4dCIsInVzZUNvbnRleHQiLCJ1c2VFZmZlY3QiLCJ1c2VNZW1vIiwidXNlU3RhdGUiLCJRdWl6Q29udGV4dCIsIkRFRkFVTFQiLCJjaXR5IiwiaG91c2Vob2xkVHlwZSIsImNoaWxkcmVuQ291bnQiLCJjaGlsZHJlbkFnZXMiLCJtb2RlIiwiYmVkcm9vbXMiLCJwcm9wZXJ0eVR5cGUiLCJidWRnZXRNaW4iLCJidWRnZXRNYXgiLCJwcmlvcml0aWVzIiwiaW5jbHVkZVdvcmtDb21tdXRlIiwid29ya1RyYW5zcG9ydCIsIndvcmtNaW51dGVzIiwid29ya0FkZHJlc3MiLCJpbmNsdWRlU2Nob29sQ29tbXV0ZSIsInNjaG9vbFRyYW5zcG9ydCIsInNjaG9vbE1pbnV0ZXMiLCJsb2FkIiwicmF3Iiwid2luZG93IiwibG9jYWxTdG9yYWdlIiwiZ2V0SXRlbSIsIkpTT04iLCJwYXJzZSIsIlF1aXpQcm92aWRlciIsImNoaWxkcmVuIiwic3RhdGUiLCJzZXRTdGF0ZSIsInNldEl0ZW0iLCJzdHJpbmdpZnkiLCJ2YWx1ZSIsIlByb3ZpZGVyIiwidXNlUXVpeiIsImN0eCIsIkVycm9yIiwicmVzZXRRdWl6IiwicmVtb3ZlSXRlbSJdLCJzb3VyY2VSb290IjoiIn0=\n//# sourceURL=webpack-internal:///./components/quizState.js\n");

/***/ }),

/***/ "./pages/_app.js":
/*!***********************!*\
  !*** ./pages/_app.js ***!
  \***********************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
eval("__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   \"default\": () => (/* binding */ App)\n/* harmony export */ });\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react/jsx-dev-runtime */ \"react/jsx-dev-runtime\");\n/* harmony import */ var react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__);\n/* harmony import */ var _styles_globals_css__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ../styles/globals.css */ \"./styles/globals.css\");\n/* harmony import */ var _styles_globals_css__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_styles_globals_css__WEBPACK_IMPORTED_MODULE_1__);\n/* harmony import */ var _components_quizState__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! ../components/quizState */ \"./components/quizState.js\");\n\n\n\nfunction App({ Component, pageProps }) {\n    return /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(_components_quizState__WEBPACK_IMPORTED_MODULE_2__.QuizProvider, {\n        children: /*#__PURE__*/ (0,react_jsx_dev_runtime__WEBPACK_IMPORTED_MODULE_0__.jsxDEV)(Component, {\n            ...pageProps\n        }, void 0, false, {\n            fileName: \"C:\\\\Users\\\\nlabuzov\\\\Desktop\\\\Nikita\\\\Projects\\\\relocation-ai-assistant\\\\relocation-brief-webapp\\\\frontend\\\\pages\\\\_app.js\",\n            lineNumber: 7,\n            columnNumber: 7\n        }, this)\n    }, void 0, false, {\n        fileName: \"C:\\\\Users\\\\nlabuzov\\\\Desktop\\\\Nikita\\\\Projects\\\\relocation-ai-assistant\\\\relocation-brief-webapp\\\\frontend\\\\pages\\\\_app.js\",\n        lineNumber: 6,\n        columnNumber: 5\n    }, this);\n}\n//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiLi9wYWdlcy9fYXBwLmpzIiwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7QUFBOEI7QUFDd0I7QUFFdkMsU0FBU0MsSUFBSSxFQUFFQyxTQUFTLEVBQUVDLFNBQVMsRUFBRTtJQUNsRCxxQkFDRSw4REFBQ0gsK0RBQVlBO2tCQUNYLDRFQUFDRTtZQUFXLEdBQUdDLFNBQVM7Ozs7Ozs7Ozs7O0FBRzlCIiwic291cmNlcyI6WyJ3ZWJwYWNrOi8vcmVsb2NhdGlvbi1icmllZi1mcm9udGVuZC8uL3BhZ2VzL19hcHAuanM/ZTBhZCJdLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgJy4uL3N0eWxlcy9nbG9iYWxzLmNzcydcbmltcG9ydCB7IFF1aXpQcm92aWRlciB9IGZyb20gJy4uL2NvbXBvbmVudHMvcXVpelN0YXRlJ1xuXG5leHBvcnQgZGVmYXVsdCBmdW5jdGlvbiBBcHAoeyBDb21wb25lbnQsIHBhZ2VQcm9wcyB9KSB7XG4gIHJldHVybiAoXG4gICAgPFF1aXpQcm92aWRlcj5cbiAgICAgIDxDb21wb25lbnQgey4uLnBhZ2VQcm9wc30gLz5cbiAgICA8L1F1aXpQcm92aWRlcj5cbiAgKVxufVxuIl0sIm5hbWVzIjpbIlF1aXpQcm92aWRlciIsIkFwcCIsIkNvbXBvbmVudCIsInBhZ2VQcm9wcyJdLCJzb3VyY2VSb290IjoiIn0=\n//# sourceURL=webpack-internal:///./pages/_app.js\n");

/***/ }),

/***/ "./styles/globals.css":
/*!****************************!*\
  !*** ./styles/globals.css ***!
  \****************************/
/***/ (() => {



/***/ }),

/***/ "react":
/*!************************!*\
  !*** external "react" ***!
  \************************/
/***/ ((module) => {

"use strict";
module.exports = require("react");

/***/ }),

/***/ "react/jsx-dev-runtime":
/*!****************************************!*\
  !*** external "react/jsx-dev-runtime" ***!
  \****************************************/
/***/ ((module) => {

"use strict";
module.exports = require("react/jsx-dev-runtime");

/***/ })

};
;

// load runtime
var __webpack_require__ = require("../webpack-runtime.js");
__webpack_require__.C(exports);
var __webpack_exec__ = (moduleId) => (__webpack_require__(__webpack_require__.s = moduleId))
var __webpack_exports__ = (__webpack_exec__("./pages/_app.js"));
module.exports = __webpack_exports__;

})();